#include "ExtraPluginFormats.h"
#include "HostedInstance.h"
#include <array>
#include <clap/clap.h>
#include <clap/ext/audio-ports.h>
#include <clap/ext/gui.h>
#include <clap/ext/latency.h>
#include <clap/ext/log.h>
#include <clap/ext/note-ports.h>
#include <clap/ext/params.h>
#include <clap/ext/state.h>
#include <clap/ext/tail.h>
#include <clap/ext/thread-check.h>
#include <clap/ext/timer-support.h>
#include <cstring>
#include <juce_gui_extra/juce_gui_extra.h>
#if JUCE_WINDOWS
#include <windows.h>
#undef min
#undef max
#endif
namespace cydaw::plugins
{
struct ClapModule
{
    juce::DynamicLibrary library;
    const clap_plugin_entry_t *entry{};
    const clap_plugin_factory_t *factory{};
    bool initialized{};
    explicit ClapModule(const juce::File &file)
    {
        auto binary = file;
#if JUCE_MAC
        if (file.isDirectory())
        {
            auto files = file.getChildFile("Contents/MacOS").findChildFiles(juce::File::findFiles, false);
            if (!files.isEmpty())
                binary = files[0];
        }
#endif
        if (!library.open(binary.getFullPathName()))
            return;
        entry = static_cast<const clap_plugin_entry_t *>(library.getFunction("clap_entry"));
        if (!entry || !clap_version_is_compatible(entry->clap_version))
            return;
        initialized = entry->init(file.getFullPathName().toRawUTF8());
        if (initialized)
            factory = static_cast<const clap_plugin_factory_t *>(entry->get_factory(CLAP_PLUGIN_FACTORY_ID));
    }
    ~ClapModule()
    {
        if (initialized)
            entry->deinit();
    }
};
class ClapInstance;
class ClapEditor final : public juce::AudioProcessorEditor
{
    ClapInstance &owner_;
#if JUCE_WINDOWS
    juce::HWNDComponent native_;
    HWND window_{};
#endif
  public:
    explicit ClapEditor(ClapInstance &);
    ~ClapEditor() override;
    void resized() override;
};
class ClapInstance final : public HostedInstance, private juce::Timer
{
  public:
    std::shared_ptr<ClapModule> module;
    const clap_plugin_t *plugin{};
    clap_host_t host{};
    const clap_plugin_params_t *params{};
    const clap_plugin_state_t *state{};
    const clap_plugin_gui_t *gui{};
    struct Control
    {
        clap_param_info_t info;
        HostedControl *parameter{};
        double sent{};
    };
    std::vector<Control> controls;
    int presetControl{-1};
    std::vector<uint32_t> inputChannels, outputChannels;
    std::atomic<bool> callback{}, restart{}, flush{}, rescanValues{};
    bool active{}, started{}, audioThread{};
    struct Timer
    {
        clap_id id;
        uint32_t interval;
        double next;
    };
    std::vector<Timer> timers;
    clap_id nextTimer{1};
    std::atomic<uint32_t> resizeW{}, resizeH{};
    juce::Component::SafePointer<juce::AudioProcessorEditor> editor;
    alignas(8) std::array<std::array<uint8_t, 128>, 4096> events{};
    uint32_t eventCount{};
    juce::MidiBuffer result;
    juce::MidiBuffer *midiOut{};
    std::array<clap_audio_buffer_t, 16> inputs{}, outputs{};
    std::vector<float> scratch;
    std::array<float *, 64> inputPointers{}, outputPointers{};
    juce::File source;
    explicit ClapInstance(const juce::File &f) : module(std::make_shared<ClapModule>(f)), source(f)
    {
        host.clap_version = CLAP_VERSION;
        host.host_data = this;
        host.name = "CyDAW";
        host.vendor = "CyDAW";
        host.url = "https://github.com/CyberAlien";
        host.version = "2.0";
        host.request_callback = [](const clap_host_t *h) { self(h).callback = true; };
        host.request_restart = [](const clap_host_t *h) { self(h).restart = true; };
        host.request_process = [](const clap_host_t *) {};
        host.get_extension = [](const clap_host_t *, const char *id) -> const void *
        {
            static const clap_host_thread_check_t threadCheck{
                [](const clap_host_t *h) { return !self(h).audioThread; },
                [](const clap_host_t *h) { return self(h).audioThread; }};
            static const clap_host_log_t log{
                [](const clap_host_t *, clap_log_severity, const char *message)
                { juce::Logger::writeToLog("CLAP: " + juce::String::fromUTF8(message)); }};
            static const clap_host_params_t params{
                [](const clap_host_t *h, clap_param_rescan_flags flags)
                {
                    auto &s = self(h);
                    if (flags & CLAP_PARAM_RESCAN_ALL)
                        s.restart = true;
                    else
                        s.rescanValues = true;
                },
                [](const clap_host_t *, clap_id, clap_param_clear_flags) {},
                [](const clap_host_t *h) { self(h).flush = true; }};
            static const clap_host_state_t state{[](const clap_host_t *) {}};
            static const clap_host_latency_t latency{[](const clap_host_t *h) { self(h).restart = true; }};
            static const clap_host_timer_support_t timer{
                [](const clap_host_t *h, uint32_t ms, clap_id *id)
                {
                    if (!id || self(h).timers.size() >= 128)
                        return false;
                    auto &s = self(h);
                    *id = s.nextTimer++;
                    s.timers.push_back(
                        {*id, std::max(1u, ms), juce::Time::getMillisecondCounterHiRes() + ms});
                    return true;
                },
                [](const clap_host_t *h, clap_id id)
                { return std::erase_if(self(h).timers, [id](const auto &t) { return t.id == id; }) > 0; }};
            static const clap_host_gui_t gui{[](const clap_host_t *) {},
                                             [](const clap_host_t *h, uint32_t w, uint32_t v)
                                             {
                                                 if (!w || !v || w > 8192 || v > 8192)
                                                     return false;
                                                 self(h).resizeW = w;
                                                 self(h).resizeH = v;
                                                 return true;
                                             },
                                             [](const clap_host_t *h)
                                             {
                                                 if (auto *e = self(h).editor.getComponent())
                                                 {
                                                     e->setVisible(true);
                                                     return true;
                                                 }
                                                 return false;
                                             },
                                             [](const clap_host_t *h)
                                             {
                                                 if (auto *e = self(h).editor.getComponent())
                                                 {
                                                     e->setVisible(false);
                                                     return true;
                                                 }
                                                 return false;
                                             },
                                             [](const clap_host_t *h, bool)
                                             {
                                                 if (auto *e = self(h).editor.getComponent())
                                                     e->setVisible(false);
                                             }};
            if (!std::strcmp(id, CLAP_EXT_THREAD_CHECK))
                return &threadCheck;
            if (!std::strcmp(id, CLAP_EXT_LOG))
                return &log;
            if (!std::strcmp(id, CLAP_EXT_PARAMS))
                return &params;
            if (!std::strcmp(id, CLAP_EXT_STATE))
                return &state;
            if (!std::strcmp(id, CLAP_EXT_LATENCY))
                return &latency;
            if (!std::strcmp(id, CLAP_EXT_TIMER_SUPPORT))
                return &timer;
            if (!std::strcmp(id, CLAP_EXT_GUI))
                return &gui;
            return nullptr;
        };
    }
    static ClapInstance &self(const clap_host_t *h) { return *static_cast<ClapInstance *>(h->host_data); }
    bool load(const juce::String &id, juce::String &error)
    {
        if (!module->factory)
        {
            error = "CLAP: invalid binary or incompatible API";
            return false;
        }
        const clap_plugin_descriptor_t *descriptor{};
        for (uint32_t i = 0; i < module->factory->get_plugin_count(module->factory); ++i)
        {
            auto *d = module->factory->get_plugin_descriptor(module->factory, i);
            if (d && (id.isEmpty() || id == d->id))
            {
                descriptor = d;
                break;
            }
        }
        if (!descriptor)
        {
            error = "CLAP: plugin ID not found: " + id;
            return false;
        }
        plugin = module->factory->create_plugin(module->factory, &host, descriptor->id);
        if (!plugin || !plugin->init(plugin))
        {
            error = "CLAP: plugin initialization failed";
            return false;
        }
        description.name = juce::String::fromUTF8(descriptor->name);
        description.manufacturerName = juce::String::fromUTF8(descriptor->vendor);
        description.version = juce::String::fromUTF8(descriptor->version);
        description.pluginFormatName = "CLAP";
        description.fileOrIdentifier = source.getFullPathName();
        description.uniqueId = juce::String::fromUTF8(descriptor->id).hashCode();
        description.descriptiveName = juce::String::fromUTF8(descriptor->id);
        if (descriptor->features)
            for (auto f = descriptor->features; *f; ++f)
                if (!std::strcmp(*f, CLAP_PLUGIN_FEATURE_INSTRUMENT))
                    description.isInstrument = true;
        description.category = description.isInstrument ? "Instrument" : "Effect";
        auto *ports = static_cast<const clap_plugin_audio_ports_t *>(
            plugin->get_extension(plugin, CLAP_EXT_AUDIO_PORTS));
        int totalIn = 0, totalOut = 0;
        if (ports)
            for (bool input : {true, false})
            {
                auto count = ports->count(plugin, input);
                if (count > 16)
                {
                    error = "CLAP: too many audio buses";
                    return false;
                }
                for (uint32_t i = 0; i < count; ++i)
                {
                    clap_audio_port_info_t info{};
                    if (!ports->get(plugin, i, input, &info) || info.channel_count > 64)
                    {
                        error = "CLAP: invalid audio bus";
                        return false;
                    }
                    (input ? inputChannels : outputChannels).push_back(info.channel_count);
                    (input ? totalIn : totalOut) += info.channel_count;
                }
            }
        if (totalIn > 64 || totalOut > 64)
        {
            error = "CLAP: at most 64 channels are supported";
            return false;
        }
        addPorts(totalIn, totalOut);
        params = static_cast<const clap_plugin_params_t *>(plugin->get_extension(plugin, CLAP_EXT_PARAMS));
        state = static_cast<const clap_plugin_state_t *>(plugin->get_extension(plugin, CLAP_EXT_STATE));
        gui = static_cast<const clap_plugin_gui_t *>(plugin->get_extension(plugin, CLAP_EXT_GUI));
        if (params)
        {
            auto count = params->count(plugin);
            if (count > 65536)
            {
                error = "CLAP: invalid parameter count";
                return false;
            }
            for (uint32_t i = 0; i < count; ++i)
            {
                clap_param_info_t info{};
                if (!params->get_info(plugin, i, &info))
                    continue;
                auto p =
                    std::make_unique<HostedControl>(juce::String(info.id), juce::String::fromUTF8(info.name),
                                                    info.min_value, info.max_value, info.default_value);
                if (info.flags & CLAP_PARAM_IS_STEPPED)
                    p->steps = std::max(2, int(info.max_value - info.min_value + 1));
                p->automate = bool(info.flags & CLAP_PARAM_IS_AUTOMATABLE);
                double v = info.default_value;
                params->get_value(plugin, info.id, &v);
                p->value = v;
                p->display = [this, id = info.id](double value)
                {
                    char text[256]{};
                    return params->value_to_text(plugin, id, value, text, sizeof(text))
                               ? juce::String::fromUTF8(text)
                               : juce::String(value, 3);
                };
                if (presetControl < 0 && (info.flags & CLAP_PARAM_IS_ENUM) &&
                    (info.flags & CLAP_PARAM_IS_STEPPED) &&
                    juce::String::fromUTF8(info.name).equalsIgnoreCase("Preset") &&
                    info.max_value - info.min_value < 2048)
                    presetControl = int(controls.size());
                controls.push_back({info, p.get(), std::numeric_limits<double>::quiet_NaN()});
                addHostedParameter(std::move(p));
            }
        }
        startTimer(10);
        return true;
    }
    ~ClapInstance() override
    {
        stopTimer();
        releaseResources();
        if (plugin)
            plugin->destroy(plugin);
    }
    void reset() override
    {
        if (plugin && active) { audioThread = true; plugin->reset(plugin); audioThread = false; }
    }
    void prepareToPlay(double rate, int block) override
    {
        releaseResources();
        setRateAndBufferSizeDetails(rate, block);
        scratch.assign(size_t((getTotalNumInputChannels() + getTotalNumOutputChannels()) * block), 0);
        result.ensureSize(65536);
        active = plugin->activate(plugin, rate, 1, uint32_t(block));
        if (!active)
            throw std::runtime_error("CLAP activation failed");
        audioThread = true;
        started = plugin->start_processing(plugin);
        audioThread = false;
        if (!started)
            throw std::runtime_error("CLAP processing start failed");
        if (auto *l =
                static_cast<const clap_plugin_latency_t *>(plugin->get_extension(plugin, CLAP_EXT_LATENCY)))
            setLatencySamples(int(l->get(plugin)));
    }
    void releaseResources() override
    {
        if (started)
        {
            audioThread = true;
            plugin->stop_processing(plugin);
            audioThread = false;
            started = false;
        }
        if (active)
        {
            plugin->deactivate(plugin);
            active = false;
        }
    }
    template <class E> void push(const E &e)
    {
        if (eventCount < events.size() && sizeof(E) <= 128)
        {
            std::memcpy(events[eventCount++].data(), &e, sizeof(e));
        }
    }
    clap_input_events_t inputList()
    {
        return {this,
                [](const clap_input_events_t *l) { return static_cast<ClapInstance *>(l->ctx)->eventCount; },
                [](const clap_input_events_t *l, uint32_t index) -> const clap_event_header_t *
                {
                    auto *s = static_cast<ClapInstance *>(l->ctx);
                    return index < s->eventCount
                               ? reinterpret_cast<const clap_event_header_t *>(s->events[index].data())
                               : nullptr;
                }};
    }
    clap_output_events_t outputList()
    {
        return {this, [](const clap_output_events_t *l, const clap_event_header_t *e)
                {
                    auto &s = *static_cast<ClapInstance *>(l->ctx);
                    if (!e || e->space_id != CLAP_CORE_EVENT_SPACE_ID)
                        return false;
                    if (e->type == CLAP_EVENT_PARAM_VALUE && e->size >= sizeof(clap_event_param_value_t))
                    {
                        auto *v = reinterpret_cast<const clap_event_param_value_t *>(e);
                        for (auto &c : s.controls)
                            if (c.info.id == v->param_id)
                            {
                                c.parameter->value = std::clamp(v->value, c.info.min_value, c.info.max_value);
                                c.sent = c.parameter->value.load();
                                return true;
                            }
                    }
                    if (!s.midiOut)
                        return false;
                    if (e->type == CLAP_EVENT_MIDI && e->size >= sizeof(clap_event_midi_t))
                    {
                        auto *m = reinterpret_cast<const clap_event_midi_t *>(e);
                        s.midiOut->addEvent(m->data, 3, int(e->time));
                        return true;
                    }
                    if ((e->type == CLAP_EVENT_NOTE_ON || e->type == CLAP_EVENT_NOTE_OFF ||
                         e->type == CLAP_EVENT_NOTE_CHOKE) &&
                        e->size >= sizeof(clap_event_note_t))
                    {
                        auto *n = reinterpret_cast<const clap_event_note_t *>(e);
                        uint8_t m[]{uint8_t((e->type == CLAP_EVENT_NOTE_ON ? 0x90 : 0x80) |
                                            std::clamp<int>(n->channel, 0, 15)),
                                    uint8_t(std::clamp<int>(n->key, 0, 127)),
                                    uint8_t(std::clamp<int>(int(n->velocity * 127), 0, 127))};
                        s.midiOut->addEvent(m, 3, int(e->time));
                        return true;
                    }
                    return false;
                }};
    }
    void parameterEvents()
    {
        for (auto &c : controls)
        {
            double value = c.parameter->value.load();
            if (value == c.sent)
                continue;
            clap_event_param_value_t e{};
            e.header = {sizeof(e), 0, CLAP_CORE_EVENT_SPACE_ID, CLAP_EVENT_PARAM_VALUE, 0};
            e.param_id = c.info.id;
            e.cookie = c.info.cookie;
            e.note_id = -1;
            e.port_index = -1;
            e.channel = -1;
            e.key = -1;
            e.value = value;
            push(e);
            c.sent = value;
        }
    }
    void processBlock(juce::AudioBuffer<float> &buffer, juce::MidiBuffer &midi) override
    {
        if (!started)
        {
            buffer.clear();
            midi.clear();
            return;
        }
        eventCount = 0;
        parameterEvents();
        auto *notePorts =
            static_cast<const clap_plugin_note_ports_t *>(plugin->get_extension(plugin, CLAP_EXT_NOTE_PORTS));
        clap_note_port_info_t note{};
        bool nativeNotes = notePorts && notePorts->count(plugin, true) > 0 &&
                           notePorts->get(plugin, 0, true, &note) &&
                           (note.supported_dialects & CLAP_NOTE_DIALECT_CLAP);
        for (const auto m : midi)
        {
            if (m.numBytes < 1)
                continue;
            int type = m.data[0] & 0xf0;
            if (nativeNotes && m.numBytes >= 3 && (type == 0x90 || type == 0x80))
            {
                clap_event_note_t e{};
                e.header = {sizeof(e), uint32_t(std::max(0, m.samplePosition)), 0,
                            uint16_t(type == 0x90 && m.data[2] ? CLAP_EVENT_NOTE_ON : CLAP_EVENT_NOTE_OFF),
                            0};
                e.note_id = -1;
                e.port_index = 0;
                e.channel = m.data[0] & 15;
                e.key = m.data[1];
                e.velocity = m.data[2] / 127.0;
                push(e);
            }
            else if (m.numBytes <= 3)
            {
                clap_event_midi_t e{};
                e.header = {sizeof(e), uint32_t(std::max(0, m.samplePosition)), 0, CLAP_EVENT_MIDI, 0};
                std::memcpy(e.data, m.data, size_t(m.numBytes));
                push(e);
            }
            else
            {
                clap_event_midi_sysex_t e{};
                e.header = {sizeof(e), uint32_t(std::max(0, m.samplePosition)), 0, CLAP_EVENT_MIDI_SYSEX, 0};
                e.buffer = m.data;
                e.size = uint32_t(m.numBytes);
                push(e);
            }
        }
        // JUCE iterates MIDI chronologically; all parameter events precede it at time 0.
        int frames = buffer.getNumSamples(), stride = getBlockSize(), offset = 0, total = 0;
        for (size_t b = 0; b < inputChannels.size(); ++b)
        {
            auto &port = inputs[b];
            port = {};
            port.channel_count = inputChannels[b];
            port.data32 = inputPointers.data() + total;
            for (uint32_t c = 0; c < port.channel_count; ++c)
            {
                auto *data = scratch.data() + size_t(offset++) * stride;
                port.data32[c] = data;
                if (total < buffer.getNumChannels())
                    std::copy_n(buffer.getReadPointer(total), frames, data);
                else
                    std::fill_n(data, frames, 0.f);
                ++total;
            }
        }
        total = 0;
        for (size_t b = 0; b < outputChannels.size(); ++b)
        {
            auto &port = outputs[b];
            port = {};
            port.channel_count = outputChannels[b];
            port.data32 = outputPointers.data() + total;
            for (uint32_t c = 0; c < port.channel_count; ++c)
            {
                port.data32[c] = scratch.data() + size_t(offset++) * stride;
                std::fill_n(port.data32[c], frames, 0.f);
                ++total;
            }
        }
        auto in = inputList();
        auto out = outputList();
        result.clear();
        midiOut = &result;
        clap_process_t p{};
        p.frames_count = uint32_t(frames);
        p.steady_time = steady_;
        steady_ += frames;
        p.audio_inputs = inputs.data();
        p.audio_inputs_count = uint32_t(inputChannels.size());
        p.audio_outputs = outputs.data();
        p.audio_outputs_count = uint32_t(outputChannels.size());
        p.in_events = &in;
        p.out_events = &out;
        clap_event_transport_t transport{};
        transport.header = {sizeof(transport), 0, 0, CLAP_EVENT_TRANSPORT, 0};
        if (auto *play = getPlayHead())
            if (auto pos = play->getPosition())
            {
                transport.flags = CLAP_TRANSPORT_HAS_TEMPO | CLAP_TRANSPORT_HAS_SECONDS_TIMELINE |
                                  CLAP_TRANSPORT_HAS_BEATS_TIMELINE | CLAP_TRANSPORT_HAS_TIME_SIGNATURE |
                                  (pos->getIsPlaying() ? CLAP_TRANSPORT_IS_PLAYING : 0);
                transport.tempo = pos->getBpm().orFallback(120.0);
                transport.song_pos_seconds =
                    int64_t(pos->getTimeInSeconds().orFallback(0.0) * CLAP_SECTIME_FACTOR);
                transport.song_pos_beats =
                    int64_t(pos->getPpqPosition().orFallback(0.0) * CLAP_BEATTIME_FACTOR);
                auto sig = pos->getTimeSignature().orFallback(juce::AudioPlayHead::TimeSignature{});
                transport.tsig_num = uint16_t(sig.numerator);
                transport.tsig_denom = uint16_t(sig.denominator);
                p.transport = &transport;
            }
        audioThread = true;
        auto status = plugin->process(plugin, &p);
        audioThread = false;
        midiOut = nullptr;
        buffer.clear();
        if (status != CLAP_PROCESS_ERROR)
            for (int c = 0; c < std::min(total, buffer.getNumChannels()); ++c)
                std::copy_n(outputPointers[c], frames, buffer.getWritePointer(c));
        midi.swapWith(result);
    }
    int64_t steady_{};
    void timerCallback() override
    {
        if (rescanValues.exchange(false) && params)
            for (auto &c : controls)
            {
                double value{};
                if (params->get_value(plugin, c.info.id, &value) && std::isfinite(value))
                {
                    c.parameter->value = std::clamp(value, c.info.min_value, c.info.max_value);
                    c.sent = c.parameter->value.load();
                }
            }

        if (callback.exchange(false))
            plugin->on_main_thread(plugin);
        if (restart.exchange(false) && active)
        {
            auto rate = getSampleRate();
            auto block = getBlockSize();
            prepareToPlay(rate, block);
        }
        if (flush.exchange(false) && params && !audioThread)
        {
            eventCount = 0;
            parameterEvents();
            auto in = inputList();
            auto out = outputList();
            audioThread = active;
            params->flush(plugin, &in, &out);
            audioThread = false;
        }
        auto copy = timers;
        double now = juce::Time::getMillisecondCounterHiRes();
        for (auto t : copy)
            if (now >= t.next)
            {
                for (auto &original : timers)
                    if (original.id == t.id)
                        original.next = now + t.interval;
                if (auto *timer = static_cast<const clap_plugin_timer_support_t *>(
                        plugin->get_extension(plugin, CLAP_EXT_TIMER_SUPPORT)))
                    timer->on_timer(plugin, t.id);
            }
        auto w = resizeW.exchange(0), h = resizeH.exchange(0);
        if (w && h)
            if (auto *e = editor.getComponent())
                e->setSize(int(w), int(h));
    }
    void getStateInformation(juce::MemoryBlock &block) override
    {
        if (state)
        {
            juce::MemoryOutputStream out(block, false);
            clap_ostream_t stream{
                &out, [](const clap_ostream_t *s, const void *data, uint64_t size) -> int64_t
                {
                    auto *o = static_cast<juce::MemoryOutputStream *>(s->ctx);
                    if (size > 16 * 1024 * 1024 || o->getDataSize() + size > 16 * 1024 * 1024)
                        return -1;
                    return o->write(data, size_t(size)) ? int64_t(size) : -1;
                }};
            if (!state->save(plugin, &stream))
                block.reset();
        }
        else
        {
            juce::MemoryOutputStream out(block, false);
            out.writeInt(0x43594350);
            out.writeInt(int(controls.size()));
            for (auto &c : controls)
            {
                out.writeInt(c.info.id);
                out.writeDouble(c.parameter->value.load());
            }
        }
    }
    void setStateInformation(const void *data, int bytes) override
    {
        if (bytes < 0)
            return;
        juce::MemoryInputStream in(data, size_t(bytes), false);
        if (state)
        {
            clap_istream_t stream{&in, [](const clap_istream_t *s, void *target, uint64_t size) -> int64_t
                                  {
                                      return static_cast<juce::MemoryInputStream *>(s->ctx)->read(
                                          target, int(std::min<uint64_t>(size, INT_MAX)));
                                  }};
            if (!state->load(plugin, &stream))
                return;
        }
        else
        {
            if (in.readInt() != 0x43594350)
                return;
            int n = in.readInt();
            if (n < 0 || n > 65536 || in.getNumBytesRemaining() < n * 12)
                return;
            for (int i = 0; i < n; ++i)
            {
                auto id = uint32_t(in.readInt());
                double v = in.readDouble();
                for (auto &c : controls)
                    if (c.info.id == id && std::isfinite(v))
                        c.parameter->value = std::clamp(v, c.info.min_value, c.info.max_value);
            }
        }
        if (state && params)
            for (auto &c : controls)
            {
                double value{};
                if (params->get_value(plugin, c.info.id, &value))
                    c.parameter->value = value;
            }
        for (auto &c : controls)
            c.sent = state && params ? c.parameter->value.load() : std::numeric_limits<double>::quiet_NaN();
    }
    int getNumPrograms() override
    {
        if (presetControl < 0)
            return 1;
        const auto &p = controls[size_t(presetControl)].info;
        return std::max(1, int(p.max_value - p.min_value) + 1);
    }
    int getCurrentProgram() override
    {
        if (presetControl < 0)
            return 0;
        const auto &p = controls[size_t(presetControl)];
        return std::clamp(int(std::round(p.parameter->value.load() - p.info.min_value)), 0,
                          getNumPrograms() - 1);
    }
    const juce::String getProgramName(int index) override
    {
        if (presetControl < 0)
            return "Default";
        if (index < 0 || index >= getNumPrograms())
            return {};
        const auto &p = controls[size_t(presetControl)];
        char text[256]{};
        return params->value_to_text(plugin, p.info.id, p.info.min_value + index, text, sizeof(text))
                   ? juce::String::fromUTF8(text)
                   : juce::String(index + 1);
    }
    void setCurrentProgram(int index) override
    {
        if (presetControl < 0 || index < 0 || index >= getNumPrograms())
            return;
        auto &p = controls[size_t(presetControl)];
        p.parameter->value = p.info.min_value + index;
        p.sent = std::numeric_limits<double>::quiet_NaN();
        eventCount = 0;
        parameterEvents();
        auto input = inputList();
        auto output = outputList();
        audioThread = active;
        params->flush(plugin, &input, &output);
        audioThread = false;
    }
    double getTailLengthSeconds() const override
    {
        if (auto *tail =
                static_cast<const clap_plugin_tail_t *>(plugin->get_extension(plugin, CLAP_EXT_TAIL)))
            return tail->get(plugin) / std::max(1.0, getSampleRate());
        return 0;
    }
    juce::AudioProcessorEditor *createEditor() override
    {
#if JUCE_WINDOWS
        if (gui && gui->is_api_supported(plugin, CLAP_WINDOW_API_WIN32, false) &&
            gui->create(plugin, CLAP_WINDOW_API_WIN32, false))
            return new ClapEditor(*this);
#endif
        return HostedInstance::createEditor();
    }
};
ClapEditor::ClapEditor(ClapInstance &p) : AudioProcessorEditor(p), owner_(p)
{
#if JUCE_WINDOWS
    window_ = CreateWindowExW(0, L"STATIC", L"", WS_CHILD, 0, 0, 1, 1, GetDesktopWindow(), nullptr,
                              GetModuleHandleW(nullptr), nullptr);
    native_.setHWND(window_);
    addAndMakeVisible(native_);
    clap_window_t parent{};
    parent.api = CLAP_WINDOW_API_WIN32;
    parent.win32 = window_;
    if (!p.gui->set_parent(p.plugin, &parent))
        throw std::runtime_error("CLAP editor attachment failed");
    uint32_t w = 640, h = 420;
    p.gui->get_size(p.plugin, &w, &h);
    p.editor = this;
    setResizable(p.gui->can_resize(p.plugin), false);
    setSize(int(w), int(h));
    p.gui->show(p.plugin);
#endif
}
ClapEditor::~ClapEditor()
{
    owner_.editor = nullptr;
    owner_.gui->hide(owner_.plugin);
    owner_.gui->destroy(owner_.plugin);
#if JUCE_WINDOWS
    native_.setHWND(nullptr);
    if (window_)
        DestroyWindow(window_);
#endif
}
void ClapEditor::resized()
{
#if JUCE_WINDOWS
    native_.setBounds(getLocalBounds());
    if (owner_.gui->can_resize(owner_.plugin))
    {
        uint32_t w = uint32_t(getWidth()), h = uint32_t(getHeight());
        owner_.gui->adjust_size(owner_.plugin, &w, &h);
        owner_.gui->set_size(owner_.plugin, w, h);
    }
#endif
}
std::unique_ptr<juce::AudioPluginInstance> createClap(const juce::File &f, const juce::String &id,
                                                      juce::String &error)
{
    auto p = std::make_unique<ClapInstance>(f);
    if (!p->load(id, error))
        return {};
    return p;
}
void scanClap(const juce::File &f, juce::OwnedArray<juce::PluginDescription> &result, juce::String &error)
{
    ClapModule module(f);
    if (!module.factory)
    {
        error = "Invalid CLAP library";
        return;
    }
    for (uint32_t i = 0; i < module.factory->get_plugin_count(module.factory); ++i)
    {
        auto *d = module.factory->get_plugin_descriptor(module.factory, i);
        if (!d)
            continue;
        auto desc = std::make_unique<juce::PluginDescription>();
        desc->name = juce::String::fromUTF8(d->name);
        desc->manufacturerName = juce::String::fromUTF8(d->vendor);
        desc->version = juce::String::fromUTF8(d->version);
        desc->descriptiveName = juce::String::fromUTF8(d->id);
        desc->uniqueId = desc->descriptiveName.hashCode();
        desc->fileOrIdentifier = f.getFullPathName();
        desc->pluginFormatName = "CLAP";
        if (d->features)
            for (auto feature = d->features; *feature; ++feature)
                if (!std::strcmp(*feature, CLAP_PLUGIN_FEATURE_INSTRUMENT))
                    desc->isInstrument = true;
        desc->category = desc->isInstrument ? "Instrument" : "Effect";
        result.add(std::move(desc));
    }
}
} // namespace cydaw::plugins
