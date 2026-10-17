#include "ExtraPluginFormats.h"
#include "HostedInstance.h"
#include <array>
#include <ysfx.h>
namespace cydaw::plugins
{
class JsfxInstance;
class JsfxGraphics final : public juce::Component, private juce::Timer
{
    JsfxInstance &owner_;
    juce::Image frame_;
    double wheel_{};
    void timerCallback() override;
    void mouse(const juce::MouseEvent &);

  public:
    explicit JsfxGraphics(JsfxInstance &);
    ~JsfxGraphics() override { stopTimer(); }
    void paint(juce::Graphics &g) override { g.drawImageAt(frame_, 0, 0); }
    void resized() override
    {
        frame_ = juce::Image(juce::Image::ARGB, std::max(1, getWidth()), std::max(1, getHeight()), true);
    }
    void mouseMove(const juce::MouseEvent &e) override { mouse(e); }
    void mouseDrag(const juce::MouseEvent &e) override { mouse(e); }
    void mouseDown(const juce::MouseEvent &e) override
    {
        grabKeyboardFocus();
        mouse(e);
    }
    void mouseUp(const juce::MouseEvent &e) override { mouse(e); }
    void mouseWheelMove(const juce::MouseEvent &e, const juce::MouseWheelDetails &d) override
    {
        wheel_ += d.deltaY * 10;
        mouse(e);
    }
    bool keyPressed(const juce::KeyPress &) override;
};
class JsfxInstance final : public HostedInstance
{
  public:
    ysfx_config_u config{ysfx_config_new()};
    ysfx_u fx;
    std::vector<std::pair<int, HostedControl *>> controls;
    juce::String diagnostics;
    juce::File source;
    explicit JsfxInstance(const juce::File &file) : source(file)
    {
        ysfx_set_user_data(config.get(), reinterpret_cast<intptr_t>(this));
        ysfx_set_log_reporter(config.get(),
                              [](intptr_t data, ysfx_log_level level, const char *message)
                              {
                                  auto *self = reinterpret_cast<JsfxInstance *>(data);
                                  if (self->diagnostics.length() < 65536)
                                      self->diagnostics += juce::String(ysfx_log_level_string(level)) + ": " +
                                                           juce::String::fromUTF8(message) + "\n";
                              });
        ysfx_guess_file_roots(config.get(), file.getFullPathName().toRawUTF8());
        ysfx_register_builtin_audio_formats(config.get());
        fx.reset(ysfx_new(config.get()));
    }
    bool load(juce::String &error)
    {
        if (!fx || !ysfx_load_file(fx.get(), source.getFullPathName().toRawUTF8(), 0) ||
            !ysfx_compile(fx.get(), 0))
        {
            error =
                diagnostics.isNotEmpty() ? diagnostics : "JSFX: cannot compile " + source.getFullPathName();
            return false;
        }
        description.name = juce::String::fromUTF8(ysfx_get_name(fx.get()));
        if (description.name.isEmpty())
            description.name = source.getFileNameWithoutExtension();
        description.manufacturerName = juce::String::fromUTF8(ysfx_get_author(fx.get()));
        description.pluginFormatName = "JSFX";
        description.fileOrIdentifier = source.getFullPathName();
        description.uniqueId = description.fileOrIdentifier.hashCode();
        description.category = "Effect";
        description.version = "1";
        addPorts(std::clamp<int>(ysfx_get_num_inputs(fx.get()), 0, 64),
                 std::clamp<int>(ysfx_get_num_outputs(fx.get()), 0, 64));
        description.isInstrument = description.numInputChannels == 0;
        for (int i = 0; i < ysfx_max_sliders; ++i)
            if (ysfx_slider_exists(fx.get(), i))
            {
                ysfx_slider_range_t range{};
                ysfx_slider_get_range(fx.get(), i, &range);
                auto p = std::make_unique<HostedControl>(
                    "slider" + juce::String(i + 1), juce::String::fromUTF8(ysfx_slider_get_name(fx.get(), i)),
                    range.min, range.max, range.def);
                if (ysfx_slider_is_enum(fx.get(), i))
                {
                    juce::StringArray labels;
                    for (uint32_t j = 0; j < ysfx_slider_get_enum_size(fx.get(), i); ++j)
                        labels.add(juce::String::fromUTF8(ysfx_slider_get_enum_name(fx.get(), i, j)));
                    p->steps = labels.size();
                    p->display = [labels, lo = range.min](double v)
                    { return labels[juce::jlimit(0, labels.size() - 1, int(std::round(v - lo)))]; };
                }
                controls.emplace_back(i, p.get());
                addHostedParameter(std::move(p));
            }
        return true;
    }
    void prepareToPlay(double rate, int block) override
    {
        setRateAndBufferSizeDetails(rate, block);
        ysfx_set_sample_rate(fx.get(), rate);
        ysfx_set_block_size(fx.get(), block);
        ysfx_set_midi_capacity(fx.get(), 65536, false);
        ysfx_init(fx.get());
        syncSliders();
    }
    void syncSliders()
    {
        for (auto [index, p] : controls)
            p->value.store(ysfx_slider_get_value(fx.get(), index));
    }
    void releaseResources() override {}
    void processBlock(juce::AudioBuffer<float> &buffer, juce::MidiBuffer &midi) override
    {
        for (auto [index, p] : controls)
            ysfx_slider_set_value(fx.get(), index, p->value.load());
        if (auto *play = getPlayHead())
            if (auto position = play->getPosition())
            {
                ysfx_time_info_t t{};
                t.tempo = position->getBpm().orFallback(120.0);
                t.playback_state = position->getIsPlaying() ? ysfx_playback_playing : ysfx_playback_paused;
                t.time_position = position->getTimeInSeconds().orFallback(0.0);
                t.beat_position = position->getPpqPosition().orFallback(0.0);
                auto sig = position->getTimeSignature().orFallback(juce::AudioPlayHead::TimeSignature{});
                t.time_signature[0] = sig.numerator;
                t.time_signature[1] = sig.denominator;
                ysfx_set_time_info(fx.get(), &t);
            }
        for (const auto item : midi)
        {
            ysfx_midi_event_t e{0, uint32_t(std::max(0, item.samplePosition)), uint32_t(item.numBytes),
                                item.data};
            ysfx_send_midi(fx.get(), &e);
        }
        auto ni = std::min(getTotalNumInputChannels(), buffer.getNumChannels()),
             no = std::min(getTotalNumOutputChannels(), buffer.getNumChannels());
        ysfx_process_float(fx.get(), buffer.getArrayOfReadPointers(), buffer.getArrayOfWritePointers(), ni,
                           no, buffer.getNumSamples());
        midi.clear();
        ysfx_midi_event_t e{};
        while (ysfx_receive_midi(fx.get(), &e))
            if (e.bus == 0 && e.size <= 65536)
                midi.addEvent(e.data, int(e.size), std::clamp<int>(e.offset, 0, buffer.getNumSamples() - 1));
        for (int c = no; c < buffer.getNumChannels(); ++c)
            buffer.clear(c, 0, buffer.getNumSamples());
        syncSliders();
        setLatencySamples(std::max(0, int(ysfx_get_pdc_delay(fx.get()))));
    }
    void getStateInformation(juce::MemoryBlock &block) override
    {
        for (auto [index, p] : controls)
            ysfx_slider_set_value(fx.get(), index, p->value.load());
        ysfx_state_u state{ysfx_save_state(fx.get())};
        if (!state)
            return;
        juce::MemoryOutputStream out(block, false);
        out.writeInt(0x43594a53);
        out.writeInt(1);
        out.writeInt(int(state->slider_count));
        for (uint32_t i = 0; i < state->slider_count; ++i)
        {
            out.writeInt(state->sliders[i].index);
            out.writeDouble(state->sliders[i].value);
        }
        out.writeInt64(state->data_size);
        out.write(state->data, state->data_size);
    }
    void setStateInformation(const void *data, int bytes) override
    {
        juce::MemoryInputStream in(data, size_t(std::max(0, bytes)), false);
        if (in.readInt() != 0x43594a53 || in.readInt() != 1)
            return;
        int count = in.readInt();
        if (count < 0 || count > 64 || in.getNumBytesRemaining() < count * 12 + 8)
            return;
        std::vector<ysfx_state_slider_t> sliders;
        for (int i = 0; i < count; ++i)
        {
            int index = in.readInt();
            double v = in.readDouble();
            if (index < 0 || index >= 64 || !std::isfinite(v))
                return;
            sliders.push_back({uint32_t(index), v});
        }
        auto size = in.readInt64();
        if (size < 0 || size > in.getNumBytesRemaining())
            return;
        std::vector<uint8_t> serialized(size_t(size), uint8_t{});
        in.read(serialized.data(), size_t(size));
        ysfx_state_t state{sliders.data(), uint32_t(sliders.size()), serialized.data(), serialized.size()};
        ysfx_load_state(fx.get(), &state);
        syncSliders();
    }
    juce::AudioProcessorEditor *createEditor() override;
};
class JsfxEditor final : public juce::AudioProcessorEditor
{
    juce::GenericAudioProcessorEditor sliders_;
    std::unique_ptr<JsfxGraphics> gfx_;

  public:
    explicit JsfxEditor(JsfxInstance &p) : AudioProcessorEditor(p), sliders_(p)
    {
        addAndMakeVisible(sliders_);
        uint32_t dim[2]{};
        ysfx_get_gfx_dim(p.fx.get(), dim);
        if (ysfx_has_section(p.fx.get(), ysfx_section_gfx))
        {
            gfx_ = std::make_unique<JsfxGraphics>(p);
            addAndMakeVisible(*gfx_);
        }
        setResizable(true, false);
        setSize(std::clamp<int>(dim[0] ? dim[0] : 560, 360, 1600),
                std::min(1000, sliders_.getHeight() +
                                   (gfx_ ? std::clamp<int>(dim[1] ? dim[1] : 300, 100, 700) : 0)));
    }
    void resized() override
    {
        auto r = getLocalBounds();
        sliders_.setBounds(r.removeFromTop(gfx_ ? std::min(280, getHeight() / 2) : getHeight()));
        if (gfx_)
            gfx_->setBounds(r);
    }
};
juce::AudioProcessorEditor *JsfxInstance::createEditor() { return new JsfxEditor(*this); }
JsfxGraphics::JsfxGraphics(JsfxInstance &p) : owner_(p)
{
    setWantsKeyboardFocus(true);
    startTimerHz(30);
}
static uint32_t mods(juce::ModifierKeys m)
{
    return (m.isShiftDown() ? ysfx_mod_shift : 0) | (m.isCtrlDown() ? ysfx_mod_ctrl : 0) |
           (m.isAltDown() ? ysfx_mod_alt : 0);
}
void JsfxGraphics::mouse(const juce::MouseEvent &e)
{
    ysfx_gfx_update_mouse(owner_.fx.get(), mods(e.mods), e.x, e.y,
                          (e.mods.isLeftButtonDown() ? ysfx_button_left : 0) |
                              (e.mods.isRightButtonDown() ? ysfx_button_right : 0) |
                              (e.mods.isMiddleButtonDown() ? ysfx_button_middle : 0),
                          wheel_, 0);
    wheel_ = 0;
}
bool JsfxGraphics::keyPressed(const juce::KeyPress &k)
{
    ysfx_gfx_add_key(owner_.fx.get(), mods(k.getModifiers()),
                     k.getTextCharacter() ? k.getTextCharacter() : k.getKeyCode(), true);
    return true;
}
void JsfxGraphics::timerCallback()
{
    if (!isShowing() || !frame_.isValid())
        return;
    juce::Image::BitmapData bits(frame_, juce::Image::BitmapData::readWrite);
    ysfx_gfx_config_t config{};
    config.user_data = this;
    config.pixel_width = uint32_t(getWidth());
    config.pixel_height = uint32_t(getHeight());
    config.pixel_stride = uint32_t(bits.lineStride);
    config.pixels = bits.data;
    config.scale_factor = 1;
    config.show_menu = [](void *, const char *text, int32_t, int32_t) -> int32_t
    {
        ysfx_menu_u parsed{ysfx_parse_menu(text)};
        if (!parsed)
            return 0;
        juce::PopupMenu menu;
        std::vector<juce::PopupMenu> stack;
        for (uint32_t i = 0; i < parsed->insn_count; ++i)
        {
            auto &item = parsed->insns[i];
            if (item.opcode == ysfx_menu_item)
                menu.addItem(int(item.id), juce::String::fromUTF8(item.name),
                             !(item.item_flags & ysfx_menu_item_disabled),
                             bool(item.item_flags & ysfx_menu_item_checked));
            else if (item.opcode == ysfx_menu_separator)
                menu.addSeparator();
            else if (item.opcode == ysfx_menu_sub)
            {
                stack.push_back(std::move(menu));
                menu = juce::PopupMenu();
            }
            else if (item.opcode == ysfx_menu_endsub && !stack.empty())
            {
                auto child = std::move(menu);
                menu = std::move(stack.back());
                stack.pop_back();
                menu.addSubMenu(juce::String::fromUTF8(item.name), child);
            }
        }
        return menu.show();
    };
    ysfx_gfx_setup(owner_.fx.get(), &config);
    if (ysfx_gfx_run(owner_.fx.get()))
    {
        owner_.syncSliders();
        repaint();
    }
}
std::unique_ptr<juce::AudioPluginInstance> createJsfx(const juce::File &file, juce::String &error)
{
    auto p = std::make_unique<JsfxInstance>(file);
    if (!p->load(error))
        return {};
    return p;
}
juce::var validateJsfxGraphics(juce::AudioPluginInstance &instance)
{
    auto *script = dynamic_cast<JsfxInstance *>(&instance);
    if (!script)
        return {};
    auto result = juce::DynamicObject::Ptr(new juce::DynamicObject());
    const auto present = ysfx_has_section(script->fx.get(), ysfx_section_gfx);
    result->setProperty("gfxPresent", present);
    if (present)
    {
        uint32_t dimensions[2]{};
        ysfx_get_gfx_dim(script->fx.get(), dimensions);
        const auto width = std::clamp(dimensions[0] ? dimensions[0] : 640u, 1u, 2048u),
                   height = std::clamp(dimensions[1] ? dimensions[1] : 360u, 1u, 2048u);
        std::vector<uint8_t> pixels(size_t(width) * height * 4, 0);
        ysfx_gfx_config_t graphics{};
        graphics.pixel_width = width;
        graphics.pixel_height = height;
        graphics.pixel_stride = width * 4;
        graphics.pixels = pixels.data();
        graphics.scale_factor = 1;
        ysfx_gfx_setup(script->fx.get(), &graphics);
        const auto changed = ysfx_gfx_run(script->fx.get());
        result->setProperty("gfxOk", true);
        result->setProperty("gfxChanged", changed);
        result->setProperty("gfxWidth", int(width));
        result->setProperty("gfxHeight", int(height));
    }
    return juce::var(result.get());
}
} // namespace cydaw::plugins
