#include "ExtraPluginFormats.h"
#include <cydaw/plugins/PluginIsolation.h>

#include <juce_audio_processors/juce_audio_processors.h>
#include <juce_gui_basics/juce_gui_basics.h>

#include <algorithm>
#include <cmath>
#include <atomic>
#include <cstring>
#include <exception>
#include <iostream>
#include <memory>
#include <utility>
#if JUCE_WINDOWS
#include <windows.h>
#endif

namespace {

juce::var pluginDescriptionToJson(const juce::PluginDescription& description)
{
    auto value = juce::DynamicObject::Ptr(new juce::DynamicObject());
    value->setProperty("name", description.name);
    value->setProperty("manufacturer", description.manufacturerName);
    value->setProperty("version", description.version);
    value->setProperty("category", description.category);
    value->setProperty("format", description.pluginFormatName);
    value->setProperty("identifier", description.createIdentifierString());
    value->setProperty("file", description.fileOrIdentifier);
    value->setProperty("pluginId", description.pluginFormatName == "CLAP" ? description.descriptiveName : description.fileOrIdentifier);
    value->setProperty("inputs", description.numInputChannels);
    value->setProperty("outputs", description.numOutputChannels);
    value->setProperty("instrument", description.isInstrument);
    return juce::var(value.get());
}

int runSelfTest()
{
    const cydaw::plugins::AudioBlockHeader header;
    if (header.magic != cydaw::plugins::workerProtocolMagic
        || header.protocolVersion != cydaw::plugins::workerProtocolVersion)
        return 1;

    std::cout << "{\"worker\":\"AudioStudioPluginWorker\",\"protocol\":"
              << cydaw::plugins::workerProtocolVersion
              << ",\"isolation\":\"per-instance\",\"formats\":[\"CLAP\""
#if JUCE_PLUGINHOST_VST
              << ",\"VST2\""
#endif
              << ",\"LV2\",\"JSFX\"],\"status\":\"ready\"}\n";
    return 0;
}

struct PluginFormatSelection final {
    std::unique_ptr<juce::AudioPluginFormat> format;
    juce::String name;
    juce::String error;
};

bool isVst2Candidate(const juce::File& pluginFile)
{
#if JUCE_WINDOWS
    return pluginFile.hasFileExtension("dll");
#elif JUCE_LINUX || JUCE_BSD
    return pluginFile.hasFileExtension("so");
#elif JUCE_MAC
    return pluginFile.hasFileExtension("vst");
#else
    juce::ignoreUnused(pluginFile);
    return false;
#endif
}

PluginFormatSelection formatForPlugin(const juce::File& pluginFile)
{
    if (pluginFile.hasFileExtension("cyplugin")) {
        const auto data = juce::JSON::parse(pluginFile);
        const auto path = data.getProperty("file", {}).toString();
        if (!juce::File::isAbsolutePath(path)) return {{}, {}, "Invalid plugin descriptor"};
        const juce::File target(path);
        if(target.hasFileExtension("cyplugin"))return {{}, {}, "Nested plugin descriptors are not supported"};
        return formatForPlugin(target);
    }
    if (pluginFile.hasFileExtension("lv2")) return {std::make_unique<juce::LV2PluginFormat>(), "LV2", {}};
    if (cydaw::plugins::isExtraFormat(pluginFile)) return {cydaw::plugins::extraPluginFormat(pluginFile), pluginFile.hasFileExtension("clap") ? "CLAP" : "JSFX", {}};
    if (pluginFile.hasFileExtension("vst3")) {
#if JUCE_PLUGINHOST_VST3
        return { std::make_unique<juce::VST3PluginFormat>(), "VST3", {} };
#else
        return { {}, "VST3", "This worker was built without VST3 hosting" };
#endif
    }
    if (isVst2Candidate(pluginFile)) {
#if JUCE_PLUGINHOST_VST
        return { std::make_unique<juce::VSTPluginFormat>(), "VST2", {} };
#else
        return { {}, "VST2",
                 "This worker was built without optional VST2 hosting. Rebuild with "
                 "CYDAW_ENABLE_VST2=ON and a licensed historical SDK." };
#endif
    }
    return { {}, {}, "Unsupported plugin file. Expected VST3, CLAP, LV2 or JSFX." };
}

void findPluginTypes(PluginFormatSelection& selection, const juce::File& requested, juce::OwnedArray<juce::PluginDescription>& result) {
    auto file=requested;juce::String id;
    if(file.hasFileExtension("cyplugin")) {const auto data=juce::JSON::parse(file);id=data.getProperty("id",{}).toString();file=juce::File(data.getProperty("file",{}).toString());}
    selection.format->findAllTypesForFile(result,file.getFullPathName());
    if(id.isNotEmpty())for(int i=result.size();--i>=0;)if(result[i]->descriptiveName!=id && result[i]->fileOrIdentifier!=id)result.remove(i);
}

juce::var graphStateFromPlugin(juce::AudioProcessor& processor)
{
    juce::MemoryBlock state;
    processor.getStateInformation(state);
    if (state.isEmpty())
        return {};
    if (auto xml = juce::AudioProcessor::getXmlFromBinary(
            state.getData(), static_cast<int>(state.getSize()))) {
        const auto* component = xml->getChildByName("IComponent");
        if (component == nullptr)
            return {};
        juce::MemoryBlock decoded;
        if (!decoded.fromBase64Encoding(component->getAllSubText()))
            return {};
        return juce::JSON::parse(juce::String::fromUTF8(
            static_cast<const char*>(decoded.getData()),
            static_cast<int>(decoded.getSize())));
    }
    return juce::JSON::parse(juce::String::fromUTF8(
        static_cast<const char*>(state.getData()),
        static_cast<int>(state.getSize())));
}

int probePlugin(const juce::File& pluginFile,
                const juce::File& outputFile,
                const bool validateProcessing)
{
    juce::Array<juce::var> results;
    auto selection = formatForPlugin(pluginFile);
    if (selection.format == nullptr) {
        auto failure = juce::DynamicObject::Ptr(new juce::DynamicObject());
        failure->setProperty("format", selection.name);
        failure->setProperty("file", pluginFile.getFullPathName());
        failure->setProperty("error", selection.error);
        failure->setProperty("processingOk", false);
        results.add(juce::var(failure.get()));
    }
    juce::OwnedArray<juce::PluginDescription> descriptions;
    if (selection.format != nullptr) {
        if (pluginFile.hasFileExtension("jsfx") || pluginFile.getFileExtension().isEmpty()) {
            juce::String error;auto instance=cydaw::plugins::createExtraPlugin(pluginFile,48000,512,error);
            if(instance){auto d=std::make_unique<juce::PluginDescription>();instance->fillInPluginDescription(*d);descriptions.add(std::move(d));}
            else selection.error=error;
        } else findPluginTypes(selection, pluginFile, descriptions);
    }
    if (selection.format != nullptr && descriptions.isEmpty()) {
        auto failure = juce::DynamicObject::Ptr(new juce::DynamicObject());
        failure->setProperty("format", selection.name);
        failure->setProperty("file", pluginFile.getFullPathName());
        failure->setProperty("error", selection.error.isNotEmpty() ? selection.error : "No " + selection.name + " type was found in the selected file");
        failure->setProperty("processingOk", false);
        results.add(juce::var(failure.get()));
    }
    for (const auto* description : descriptions) {
        auto result = pluginDescriptionToJson(*description);
        if (validateProcessing) {
            auto* object = result.getDynamicObject();
            juce::String error;
            try {
                auto instance = selection.format->createInstanceFromDescription(
                    *description, 48'000.0, 512, error);
                if (instance != nullptr) {
                    instance->setNonRealtime(true);
                    instance->prepareToPlay(48'000.0, 512);
                    if(auto graphics=cydaw::plugins::validateJsfxGraphics(*instance);graphics.isObject())
                        for(const auto& property:graphics.getDynamicObject()->getProperties())object->setProperty(property.name,property.value);

                    const auto editableGraphRuntime = description->name.containsIgnoreCase(
                        "CyDAW Graph Runtime");
                    auto initialGraphState = graphStateFromPlugin(*instance);
                    const auto* initialGraphRoot =
                        initialGraphState.getDynamicObject();
                    const auto graphPlugin = initialGraphRoot != nullptr
                        && static_cast<int>(
                               initialGraphRoot->getProperty("schema")) == 2
                        && initialGraphRoot->getProperty("native")
                               .getDynamicObject() != nullptr;
                    if (editableGraphRuntime) {
                        auto native = juce::DynamicObject::Ptr(
                            new juce::DynamicObject());
                        native->setProperty("schema", 1);
                        native->setProperty("outputNodeId", 3);
                        juce::Array<juce::var> nodes;
                        const auto addNode = [&nodes](const int id,
                                                     const int kind,
                                                     const double gainDb) {
                            auto node = juce::DynamicObject::Ptr(
                                new juce::DynamicObject());
                            node->setProperty("id", id);
                            node->setProperty("kind", kind);
                            auto parameters = juce::DynamicObject::Ptr(
                                new juce::DynamicObject());
                            parameters->setProperty("gainDb", gainDb);
                            node->setProperty("parameters",
                                              juce::var(parameters.get()));
                            nodes.add(juce::var(node.get()));
                        };
                        addNode(1, 1, 0.0); // input
                        addNode(2, 4, 0.0); // gain
                        addNode(3, 2, 0.0); // output
                        native->setProperty("nodes", nodes);
                        juce::Array<juce::var> connections;
                        for (const auto [source, destination]
                             : { std::pair { 1, 2 }, std::pair { 2, 3 } }) {
                            auto connection = juce::DynamicObject::Ptr(
                                new juce::DynamicObject());
                            connection->setProperty("source", source);
                            connection->setProperty("destination", destination);
                            connections.add(juce::var(connection.get()));
                        }
                        native->setProperty("connections", connections);

                        auto published = juce::DynamicObject::Ptr(
                            new juce::DynamicObject());
                        published->setProperty("id", 0x1020304);
                        published->setProperty("key", "node.2.gain.db");
                        published->setProperty("name", "Host Gain");
                        published->setProperty("unit", "dB");
                        published->setProperty("minimum", -24.0);
                        published->setProperty("maximum", 24.0);
                        published->setProperty("default", 0.0);
                        published->setProperty("targetNodeId", 2);
                        published->setProperty("targetParameter",
                                               "node.2.gain.db");
                        published->setProperty("automatable", true);
                        published->setProperty("modulatable", true);
                        published->setProperty("visibleInDevice", true);
                        published->setProperty("exportedToHost", true);
                        juce::Array<juce::var> publishedParameters;
                        publishedParameters.add(juce::var(published.get()));
                        juce::Array<juce::var> hostValues;
                        hostValues.add(0.25); // -12 dB

                        auto state = juce::DynamicObject::Ptr(
                            new juce::DynamicObject());
                        state->setProperty("schema", 2);
                        state->setProperty("native", juce::var(native.get()));
                        state->setProperty("publishedParameters",
                                           publishedParameters);
                        state->setProperty("hostValues", hostValues);
                        const auto stateJson = juce::JSON::toString(
                            juce::var(state.get()), false);
                        juce::XmlElement vstState("VST3PluginState");
                        juce::MemoryBlock componentState(
                            stateJson.toRawUTF8(),
                            stateJson.getNumBytesAsUTF8());
                        vstState.createNewChildElement("IComponent")
                            ->addTextElement(
                                componentState.toBase64Encoding());
                        juce::MemoryBlock wrappedState;
                        juce::AudioProcessor::copyXmlToBinary(vstState,
                                                              wrappedState);
                        instance->setStateInformation(
                            wrappedState.getData(),
                            static_cast<int>(wrappedState.getSize()));
                    }
                    object->setProperty("inputs",
                                        instance->getTotalNumInputChannels());
                    object->setProperty("outputs",
                                        instance->getTotalNumOutputChannels());
                    const auto channels = juce::jmax(1, instance->getTotalNumInputChannels(),
                                                      instance->getTotalNumOutputChannels());
                    juce::AudioBuffer<float> buffer(channels, 512);
                    buffer.clear();
                    for (int channel = 0; channel < instance->getTotalNumInputChannels(); ++channel)
                        for (int sample = 0; sample < buffer.getNumSamples(); ++sample)
                            buffer.setSample(channel, sample,
                                             static_cast<float>(0.05 * std::sin(
                                                 juce::MathConstants<double>::twoPi * 220.0
                                                 * sample / 48'000.0)));

                    juce::MidiBuffer midi;
                    if (description->isInstrument) {
                        midi.addEvent(juce::MidiMessage::noteOn(1, 60, 0.8f), 0);
                        midi.addEvent(juce::MidiMessage::noteOff(1, 60), 480);
                    }
                    {
                        juce::ScopedNoDenormals noDenormals;
                        instance->processBlock(buffer, midi);
                    }

                    auto peak = 0.0f;
                    auto finite = true;
                    for (int channel = 0; channel < buffer.getNumChannels(); ++channel)
                        for (int sample = 0; sample < buffer.getNumSamples(); ++sample) {
                            const auto value = buffer.getSample(channel, sample);
                            finite = finite && std::isfinite(value);
                            peak = juce::jmax(peak, std::abs(value));
                        }
                    if (graphPlugin) {
                        const auto* nativeRoot = initialGraphRoot
                            ->getProperty("native").getDynamicObject();
                        const auto* nativeNodes = nativeRoot != nullptr
                            ? nativeRoot->getProperty("nodes").getArray()
                            : nullptr;
                        object->setProperty(
                            "graphNativeNodeCount",
                            nativeNodes != nullptr ? nativeNodes->size() : 0);
                        const auto& parameters = instance->getParameters();
                        juce::AudioProcessorParameter* graphGain = nullptr;
                        juce::AudioProcessorParameter* graphPostEffect = nullptr;
                        juce::String expectedName;
                        juce::String expectedUnit;
                        juce::String expectedPostEffectName;
                        auto expectedAutomatable = true;
                        auto publishedCount = 0;
                        if (editableGraphRuntime) {
                            expectedName = "Host Gain";
                            expectedUnit = "dB";
                            publishedCount = 1;
                        } else if (const auto* published =
                                       initialGraphRoot
                                           ->getProperty("publishedParameters")
                                           .getArray()) {
                            publishedCount = published->size();
                            for (const auto& encoded : *published) {
                                const auto* value = encoded.getDynamicObject();
                                if (value == nullptr)
                                    continue;
                                const auto target = value->getProperty(
                                    "targetParameter").toString();
                                if (description->isInstrument
                                    && target.containsIgnoreCase("drive.db"))
                                    expectedPostEffectName = value->getProperty(
                                        "name").toString();
                                const auto testableAudioParameter =
                                    target.containsIgnoreCase("gain.db")
                                    || (description->isInstrument
                                        && target.containsIgnoreCase(
                                            "polyOscillator.level"));
                                if (!testableAudioParameter)
                                    continue;
                                expectedName = value->getProperty("name")
                                                   .toString();
                                expectedUnit = value->getProperty("unit")
                                                   .toString();
                                expectedAutomatable =
                                    !value->hasProperty("automatable")
                                    || static_cast<bool>(value->getProperty(
                                        "automatable"));
                            }
                        }
                        juce::Array<juce::var> parameterNames;
                        for (auto* parameter : parameters) {
                            if (parameter == nullptr)
                                continue;
                            const auto name = parameter->getName(128);
                            parameterNames.add(name);
                            if (expectedName.isNotEmpty()
                                && name == expectedName)
                                graphGain = parameter;
                            if (expectedPostEffectName.isNotEmpty()
                                && name == expectedPostEffectName)
                                graphPostEffect = parameter;
                        }
                        const auto parameterContractOk = publishedCount == 0
                            ? true
                            : parameters.size() >= publishedCount
                                  && (expectedName.isEmpty()
                                      || (graphGain != nullptr
                                          && graphGain->getLabel()
                                                 == expectedUnit
                                          && graphGain->isAutomatable()
                                                 == expectedAutomatable));
                        if (graphGain != nullptr)
                            graphGain->setValueNotifyingHost(
                                description->isInstrument ? 0.20f : 0.25f);
                        auto initialPeak = peak;
                        for (auto block = 0; block < 12; ++block) {
                            buffer.clear();
                            for (int channel = 0;
                                 channel < instance->getTotalNumInputChannels();
                                 ++channel)
                                for (int sample = 0;
                                     sample < buffer.getNumSamples(); ++sample)
                                    buffer.setSample(
                                        channel, sample,
                                        static_cast<float>(0.05 * std::sin(
                                            juce::MathConstants<double>::twoPi
                                            * 220.0 * sample / 48'000.0)));
                            juce::MidiBuffer warmupMidi;
                            if (description->isInstrument && block == 0) {
                                warmupMidi.addEvent(
                                    juce::MidiMessage::allNotesOff(1), 0);
                                warmupMidi.addEvent(
                                    juce::MidiMessage::noteOn(1, 64, 0.8f), 1);
                            }
                            instance->processBlock(buffer, warmupMidi);
                            if (block == 11) {
                                initialPeak = 0.0f;
                                for (int channel = 0;
                                     channel < buffer.getNumChannels(); ++channel)
                                    initialPeak = juce::jmax(
                                        initialPeak,
                                        buffer.getMagnitude(channel, 0,
                                                            buffer.getNumSamples()));
                            }
                        }
                        if (graphGain != nullptr)
                            graphGain->setValueNotifyingHost(
                                description->isInstrument ? 0.80f : 0.75f);
                        auto automatedPeak = 0.0f;
                        for (auto block = 0; block < 16; ++block) {
                            buffer.clear();
                            for (int channel = 0;
                                 channel < instance->getTotalNumInputChannels();
                                 ++channel)
                                for (int sample = 0;
                                     sample < buffer.getNumSamples(); ++sample)
                                    buffer.setSample(
                                        channel, sample,
                                        static_cast<float>(0.05 * std::sin(
                                            juce::MathConstants<double>::twoPi
                                            * 220.0 * sample / 48'000.0)));
                            juce::MidiBuffer automationMidi;
                            instance->processBlock(buffer, automationMidi);
                            if (block == 15)
                                for (int channel = 0;
                                     channel < buffer.getNumChannels(); ++channel)
                                    automatedPeak = juce::jmax(
                                        automatedPeak,
                                        buffer.getMagnitude(channel, 0,
                                                            buffer.getNumSamples()));
                        }
                        auto postEffectDryPeak = 0.0f;
                        auto postEffectWetPeak = 0.0f;
                        if (graphPostEffect != nullptr) {
                            graphPostEffect->setValueNotifyingHost(0.0f);
                            for (auto block = 0; block < 4; ++block) {
                                buffer.clear();
                                juce::MidiBuffer effectMidi;
                                instance->processBlock(buffer, effectMidi);
                                if (block == 3)
                                    for (auto channel = 0;
                                         channel < buffer.getNumChannels();
                                         ++channel)
                                        postEffectDryPeak = juce::jmax(
                                            postEffectDryPeak,
                                            buffer.getMagnitude(
                                                channel, 0,
                                                buffer.getNumSamples()));
                            }
                            graphPostEffect->setValueNotifyingHost(1.0f);
                            for (auto block = 0; block < 4; ++block) {
                                buffer.clear();
                                juce::MidiBuffer effectMidi;
                                instance->processBlock(buffer, effectMidi);
                                if (block == 3)
                                    for (auto channel = 0;
                                         channel < buffer.getNumChannels();
                                         ++channel)
                                        postEffectWetPeak = juce::jmax(
                                            postEffectWetPeak,
                                            buffer.getMagnitude(
                                                channel, 0,
                                                buffer.getNumSamples()));
                            }
                            object->setProperty(
                                "graphPostEffectProcessingOk",
                                postEffectDryPeak > 0.0f
                                    && postEffectWetPeak
                                           > postEffectDryPeak * 1.5f);
                            object->setProperty("graphPostEffectDryPeak",
                                                postEffectDryPeak);
                            object->setProperty("graphPostEffectWetPeak",
                                                postEffectWetPeak);
                        }
                        object->setProperty("parameterCount",
                                            static_cast<int>(parameters.size()));
                        object->setProperty("parameterNames", parameterNames);
                        object->setProperty(
                            "graphParameterLabel",
                            graphGain != nullptr ? graphGain->getLabel()
                                                 : juce::String());
                        object->setProperty(
                            "graphParameterAutomatable",
                            graphGain != nullptr && graphGain->isAutomatable());
                        object->setProperty("graphParameterContractOk",
                                            parameterContractOk);
                        object->setProperty("graphStateDetected", true);
                        object->setProperty("graphPublishedParameterCount",
                                            publishedCount);
                        object->setProperty(
                            "graphAutomationProcessingOk",
                            graphGain == nullptr
                                || (parameterContractOk && initialPeak > 0.0f
                                    && automatedPeak
                                           > initialPeak
                                                 * (description->isInstrument
                                                        ? 2.5f
                                                        : 3.0f)));
                        object->setProperty("graphInitialPeak", initialPeak);
                        object->setProperty("graphAutomatedPeak", automatedPeak);
                        if (description->isInstrument)
                            object->setProperty("graphInstrumentAudioOk",
                                                finite && peak > 0.00001f);
                    }
                    juce::MemoryBlock state;
                    instance->getStateInformation(state);
                    instance->setStateInformation(state.getData(),
                                                  static_cast<int>(state.getSize()));
                    auto editor = std::unique_ptr<juce::AudioProcessorEditor>(
                        instance->hasEditor()
                            ? instance->createEditorAndMakeActive()
                                              : nullptr);
                    const auto editorOk = !instance->hasEditor()
                        || (editor != nullptr && editor->getWidth() > 0
                            && editor->getHeight() > 0);
                    object->setProperty("processingOk", finite);
                    object->setProperty("stateRoundTripOk",
                                        state.getSize() > 0);
                    object->setProperty("editorOk", editorOk);
                    object->setProperty("latencySamples", instance->getLatencySamples());
                    object->setProperty("stateBytes", static_cast<juce::int64>(state.getSize()));
                    object->setProperty("testPeak", peak);
                    instance->releaseResources();
                } else {
                    object->setProperty("processingOk", false);
                    object->setProperty("error", error);
                }
            } catch (const std::exception& exception) {
                object->setProperty("processingOk", false);
                object->setProperty("error", exception.what());
            } catch (...) {
                object->setProperty("processingOk", false);
                object->setProperty("error", "Unknown plugin exception");
            }
        }
        results.add(std::move(result));
    }

    const auto json = juce::JSON::toString(results, true);
    if (outputFile != juce::File {}) {
        if (!outputFile.replaceWithText(json))
            return 3;
    } else {
        std::cout << json << '\n';
    }
    if (validateProcessing) {
        for (const auto& result : results) {
            const auto* object = result.getDynamicObject();
            if (object == nullptr
                || !static_cast<bool>(object->getProperty("processingOk")))
                return 4;
            if (static_cast<bool>(object->getProperty("graphStateDetected"))
                && (!static_cast<bool>(object->getProperty(
                        "graphParameterContractOk"))
                    || !static_cast<bool>(object->getProperty(
                        "graphAutomationProcessingOk"))
                    || (object->hasProperty("graphInstrumentAudioOk")
                        && !static_cast<bool>(object->getProperty(
                            "graphInstrumentAudioOk")))
                    || (object->hasProperty("graphPostEffectProcessingOk")
                        && !static_cast<bool>(object->getProperty(
                            "graphPostEffectProcessingOk")))))
                return 5;
        }
    }
    return 0;
}

juce::String argumentValue(const juce::StringArray& arguments,
                           const juce::String& key,
                           const juce::String& fallback = {})
{
    const auto index = arguments.indexOf(key);
    return index >= 0 && index + 1 < arguments.size() ? arguments[index + 1] : fallback;
}

void setWorkerStatus(cydaw::plugins::SharedPluginAudio& shared,
                     const cydaw::plugins::SharedPluginState state,
                     const juce::String& message)
{
    const auto utf8 = message.toRawUTF8();
    const auto length = std::min<std::size_t>(std::strlen(utf8), sizeof(shared.statusMessage) - 1);
    std::memcpy(shared.statusMessage, utf8, length);
    shared.statusMessage[length] = '\0';
    std::atomic_ref(shared.state).store(static_cast<std::uint32_t>(state),
                                        std::memory_order_release);
}

template <std::size_t Size>
void copyFixedText(char (&destination)[Size], const juce::String& text)
{
    const auto utf8 = text.toRawUTF8();
    const auto length = std::min<std::size_t>(std::strlen(utf8), Size - 1);
    std::memcpy(destination, utf8, length);
    destination[length] = '\0';
}

class WorkerPluginEditorWindow final : public juce::DocumentWindow {
public:
    WorkerPluginEditorWindow(const juce::String& title,
                             std::unique_ptr<juce::AudioProcessorEditor> editor)
        : DocumentWindow(title, juce::Colour(0xff17191b), allButtons)
    {
        setUsingNativeTitleBar(true);
        const auto width = juce::jmax(420, editor->getWidth());
        const auto height = juce::jmax(240, editor->getHeight());
        setContentOwned(editor.release(), true);
        setResizable(true, false);
        setResizeLimits(320, 180, 3840, 2160);
        centreWithSize(width, height);
    }

    void closeButtonPressed() override { setVisible(false); }
};

class WorkerPlayHead final : public juce::AudioPlayHead {
public:
    juce::Optional<PositionInfo> getPosition() const override { return position; }
    void update(const cydaw::plugins::SharedPluginAudio& shared, double rate) {
        position.setTimeInSeconds(shared.transportSeconds);
        position.setTimeInSamples(static_cast<juce::int64>(shared.transportSeconds*rate));
        position.setPpqPosition(shared.transportQuarterNotes);
        position.setBpm(shared.transportTempo);
        position.setIsPlaying(shared.transportPlaying!=0);
        position.setTimeSignature(TimeSignature{static_cast<int>(shared.transportNumerator),static_cast<int>(shared.transportDenominator)});
    }
private:
    PositionInfo position;
};

int runRealtimeWorker(const juce::File& pluginFile,
                      const juce::File& sharedFile,
                      const double sampleRate,
                      const int maximumBlockSize,
                      const int requestedChannels,
                      const bool passthrough, const int parentPid)
{
    if (!sharedFile.existsAsFile())
        return 10;
    juce::MemoryMappedFile mapping(sharedFile, juce::MemoryMappedFile::readWrite, false);
    auto* shared = static_cast<cydaw::plugins::SharedPluginAudio*>(mapping.getData());
    if (shared == nullptr || mapping.getSize() < sizeof(cydaw::plugins::SharedPluginAudio)
        || shared->magic != cydaw::plugins::workerProtocolMagic
        || shared->protocolVersion != cydaw::plugins::workerProtocolVersion)
        return 11;

#if JUCE_WINDOWS
    struct WorkerEvents {
        HANDLE request{}, response{}, parent{};
        ~WorkerEvents() { if(request) CloseHandle(request); if(response) CloseHandle(response); if(parent) CloseHandle(parent); }
    } events;
    const auto eventBase = juce::String("Local\\AudioStudioPlugin_") + sharedFile.getParentDirectory().getFileName();
    events.request = CreateEventW(nullptr, FALSE, FALSE, (eventBase + "_request").toWideCharPointer());
    events.response = CreateEventW(nullptr, FALSE, FALSE, (eventBase + "_response").toWideCharPointer());
    if (parentPid > 0) events.parent = OpenProcess(SYNCHRONIZE, FALSE, static_cast<DWORD>(parentPid));
#endif
    try {
        WorkerPlayHead playHead;
        std::unique_ptr<juce::AudioPluginInstance> instance;
        juce::String pluginFormatName;
        auto processingChannels = juce::jlimit(1,
                                                static_cast<int>(cydaw::plugins::maximumSharedAudioChannels),
                                                requestedChannels);
        if (!passthrough) {
            auto selection = formatForPlugin(pluginFile);
            pluginFormatName = selection.name;
            if (selection.format == nullptr) {
                setWorkerStatus(*shared, cydaw::plugins::SharedPluginState::error,
                                selection.error);
                return 12;
            }
            juce::OwnedArray<juce::PluginDescription> descriptions;
            findPluginTypes(selection, pluginFile, descriptions);
            if (descriptions.isEmpty()) {
                setWorkerStatus(*shared, cydaw::plugins::SharedPluginState::error,
                                "No " + pluginFormatName
                                    + " type was found in the selected file");
                return 13;
            }
            juce::String error;
            instance = selection.format->createInstanceFromDescription(
                *descriptions[0], sampleRate, maximumBlockSize, error);
            if (instance == nullptr) {
                setWorkerStatus(*shared, cydaw::plugins::SharedPluginState::error,
                                error.isNotEmpty() ? error
                                                   : "Cannot instantiate "
                                                         + pluginFormatName + " plugin");
                return 14;
            }
            instance->setPlayHead(&playHead);
            instance->setNonRealtime(false);
            instance->prepareToPlay(sampleRate, maximumBlockSize);
            processingChannels = juce::jlimit(1,
                                               static_cast<int>(cydaw::plugins::maximumSharedAudioChannels),
                                               std::max({ processingChannels,
                                                          instance->getTotalNumInputChannels(),
                                                          instance->getTotalNumOutputChannels() }));
            std::atomic_ref(shared->latencySamples).store(
                static_cast<std::uint32_t>(std::max(0, instance->getLatencySamples())),
                std::memory_order_release);
        }

        juce::AudioBuffer<float> buffer(processingChannels, maximumBlockSize);
        juce::MidiBuffer midi;
        std::unique_ptr<WorkerPluginEditorWindow> editorWindow;
        setWorkerStatus(*shared, cydaw::plugins::SharedPluginState::ready,
                        passthrough ? "IPC passthrough ready"
                                    : pluginFormatName + " ready");
        auto request = std::atomic_ref(shared->requestSequence);
        auto response = std::atomic_ref(shared->responseSequence);
        auto heartbeat = std::atomic_ref(shared->heartbeat);
        auto commandRequest = std::atomic_ref(shared->commandSequence);
        auto commandResponse = std::atomic_ref(shared->commandResponseSequence);
        auto automationRequest = std::atomic_ref(shared->automationSequence);
        std::uint64_t appliedAutomationSequence {};
        auto shutdown = std::atomic_ref(shared->shutdownRequested);

        while (shutdown.load(std::memory_order_acquire) == 0) {
#if JUCE_WINDOWS
            if (events.parent && WaitForSingleObject(events.parent, 0) == WAIT_OBJECT_0) break;
#endif
            auto didWork = false;
            const auto requested = request.load(std::memory_order_acquire);
            if (requested != response.load(std::memory_order_relaxed)) {
                const auto frames = static_cast<int>(shared->frameCount);
                const auto inputs = juce::jlimit(0, processingChannels,
                                                  static_cast<int>(shared->inputChannels));
                const auto outputs = juce::jlimit(0, processingChannels,
                                                   static_cast<int>(shared->outputChannels));
                if (frames <= 0 || frames > maximumBlockSize
                    || frames > static_cast<int>(cydaw::plugins::maximumSharedAudioFrames)) {
                    setWorkerStatus(*shared, cydaw::plugins::SharedPluginState::error,
                                    "Invalid audio block received from host");
                    return 15;
                }

                buffer.clear();
                for (int channel = 0; channel < inputs; ++channel)
                    for (int frame = 0; frame < frames; ++frame)
                        buffer.setSample(channel, frame, shared->input[
                            cydaw::plugins::sharedAudioIndex(static_cast<std::uint32_t>(channel),
                                                             static_cast<std::uint32_t>(frame))]);
                midi.clear();
                if (instance != nullptr) {
                    const auto automationSequence = automationRequest.load(std::memory_order_acquire);
                    if (automationSequence != appliedAutomationSequence) {
                        const auto& parameters = instance->getParameters();
                        const auto count = std::min(shared->automationCount,
                                                    cydaw::plugins::maximumSharedAutomationParameters);
                        for (std::uint32_t automationIndex = 0;
                             automationIndex < count;
                             ++automationIndex) {
                            const auto& automation = shared->automation[automationIndex];
                            if (automation.index < static_cast<std::uint32_t>(parameters.size()))
                                parameters[static_cast<int>(automation.index)]->setValue(
                                    juce::jlimit(0.0f, 1.0f, automation.value));
                        }
                        appliedAutomationSequence = automationSequence;
                    }
                    juce::ScopedNoDenormals noDenormals;
                    playHead.update(*shared,sampleRate);
                    instance->processBlock(buffer, midi);
                    std::atomic_ref(shared->latencySamples).store(
                        static_cast<std::uint32_t>(std::max(0, instance->getLatencySamples())),
                        std::memory_order_release);
                }
                for (int channel = 0; channel < outputs; ++channel)
                    for (int frame = 0; frame < frames; ++frame)
                        shared->output[cydaw::plugins::sharedAudioIndex(
                            static_cast<std::uint32_t>(channel), static_cast<std::uint32_t>(frame))]
                            = buffer.getSample(channel, frame);
                shared->outputFrameCount = static_cast<std::uint32_t>(frames);
                heartbeat.fetch_add(1, std::memory_order_relaxed);
                response.store(requested, std::memory_order_release);
#if JUCE_WINDOWS
                if(events.response) SetEvent(events.response);
#endif
                didWork = true;
            }

            const auto commandSequence = commandRequest.load(std::memory_order_acquire);
            if (commandSequence != commandResponse.load(std::memory_order_relaxed)) {
                shared->commandResult = 0;
                shared->commandStatus[0] = '\0';
                const auto command = static_cast<cydaw::plugins::SharedPluginCommand>(shared->command);
                if (command == cydaw::plugins::SharedPluginCommand::refreshParameters) {
                    shared->parameterCount = 0;
                    if (instance != nullptr) {
                        const auto& parameters = instance->getParameters();
                        const auto count = std::min<int>(parameters.size(),
                                                         cydaw::plugins::maximumSharedPluginParameters);
                        shared->parameterCount = static_cast<std::uint32_t>(count);
                        for (int index = 0; index < count; ++index) {
                            const auto* parameter = parameters[index];
                            auto& destination = shared->parameters[index];
                            destination.index = static_cast<std::uint32_t>(index);
                            destination.flags = (parameter->isAutomatable()
                                                     ? cydaw::plugins::parameterAutomatable : 0u)
                                                | (parameter->isDiscrete()
                                                       ? cydaw::plugins::parameterDiscrete : 0u)
                                                | (parameter->isBoolean()
                                                       ? cydaw::plugins::parameterBoolean : 0u);
                            destination.value = parameter->getValue();
                            copyFixedText(destination.name, parameter->getName(95));
                            copyFixedText(destination.label, parameter->getLabel());
                            copyFixedText(destination.text, parameter->getCurrentValueAsText());
                        }
                    }
                } else if (command == cydaw::plugins::SharedPluginCommand::setParameter) {
                    if (instance == nullptr
                        || shared->commandParameterIndex
                               >= static_cast<std::uint32_t>(instance->getParameters().size())) {
                        shared->commandResult = 1;
                        copyFixedText(shared->commandStatus, "Unknown plugin parameter");
                    } else {
                        instance->getParameters()[static_cast<int>(shared->commandParameterIndex)]
                            ->setValueNotifyingHost(juce::jlimit(0.0f, 1.0f,
                                                                 shared->commandParameterValue));
                    }
                } else if (command == cydaw::plugins::SharedPluginCommand::getState) {
                    juce::MemoryBlock state;
                    if (instance != nullptr)
                        instance->getStateInformation(state);
                    if (state.getSize() > cydaw::plugins::maximumSharedPluginStateBytes) {
                        shared->commandResult = 1;
                        copyFixedText(shared->commandStatus, "Plugin state exceeds 4 MB limit");
                    } else {
                        shared->stateBytes = static_cast<std::uint32_t>(state.getSize());
                        if (!state.isEmpty())
                            std::memcpy(shared->stateData, state.getData(), state.getSize());
                    }
                } else if (command == cydaw::plugins::SharedPluginCommand::setState) {
                    if (shared->stateBytes > cydaw::plugins::maximumSharedPluginStateBytes) {
                        shared->commandResult = 1;
                        copyFixedText(shared->commandStatus, "Invalid plugin state size");
                    } else if (instance != nullptr) {
                        instance->setStateInformation(shared->stateData,
                                                      static_cast<int>(shared->stateBytes));
                    }
                } else if (command == cydaw::plugins::SharedPluginCommand::showEditor) {
                    if (instance == nullptr || !instance->hasEditor()) {
                        shared->commandResult = 1;
                        copyFixedText(shared->commandStatus, "This plugin has no graphical editor");
                    } else {
                        if (editorWindow == nullptr) {
                            auto editor = std::unique_ptr<juce::AudioProcessorEditor>(instance->createEditorAndMakeActive());
                            if (editor != nullptr)
                                editorWindow = std::make_unique<WorkerPluginEditorWindow>(
                                    instance->getName() + " — AudioStudio", std::move(editor));
                        }
                        if (editorWindow == nullptr) {
                            shared->commandResult = 1;
                            copyFixedText(shared->commandStatus, "Plugin editor could not be created");
                        } else {
                            editorWindow->setVisible(true);
                            editorWindow->toFront(true);
                        }
                    }
                } else if (static_cast<int>(command) == 9) {
                    if (instance) {
                        std::vector<float> values;
                        for(auto* p:instance->getParameters()) values.push_back(p->getValue());
                        if(pluginFormatName == "CLAP") instance->reset();
                        else { instance->releaseResources(); instance->prepareToPlay(sampleRate, maximumBlockSize); }
                        for(int i=0;i<static_cast<int>(values.size());++i) instance->getParameters()[i]->setValue(values[static_cast<size_t>(i)]);
                    }
                } else if (command == cydaw::plugins::SharedPluginCommand::hideEditor) {
                    if (editorWindow != nullptr)
                        editorWindow->setVisible(false);
                } else if (command == cydaw::plugins::SharedPluginCommand::getPrograms) {
                    juce::String names;
                    auto count = 0;
                    if (instance != nullptr) {
                        count = std::clamp(instance->getNumPrograms(), 0, 4096);
                        for (int index = 0; index < count; ++index)
                            names << (index > 0 ? "\n" : "")
                                  << instance->getProgramName(index).replaceCharacters("\r\n", "  ");
                        shared->commandParameterIndex
                            = static_cast<std::uint32_t>(std::max(0, instance->getCurrentProgram()));
                    }
                    const auto bytes = std::min<std::size_t>(names.getNumBytesAsUTF8(),
                                                             cydaw::plugins::maximumSharedPluginStateBytes);
                    if (bytes > 0)
                        std::memcpy(shared->stateData, names.toRawUTF8(), bytes);
                    shared->stateBytes = static_cast<std::uint32_t>(bytes);
                    shared->commandParameterValue = static_cast<float>(count);
                } else if (command == cydaw::plugins::SharedPluginCommand::setProgram) {
                    if (instance == nullptr
                        || shared->commandParameterIndex
                               >= static_cast<std::uint32_t>(std::max(0, instance->getNumPrograms()))) {
                        shared->commandResult = 1;
                        copyFixedText(shared->commandStatus, "Unknown plugin program");
                    } else {
                        instance->setCurrentProgram(static_cast<int>(shared->commandParameterIndex));
                    }
                }
                commandResponse.store(commandSequence, std::memory_order_release);
#if JUCE_WINDOWS
                if(events.response) SetEvent(events.response);
#endif
                didWork = true;
            }

            const auto now = juce::Time::getMillisecondCounter();
            static juce::uint32 lastDispatch{};
            if (now - lastDispatch >= 20) { juce::MessageManager::getInstance()->runDispatchLoopUntil(1); lastDispatch = now; }
            shared->reserved = editorWindow && editorWindow->isVisible() ? 1 : 0;
#if JUCE_WINDOWS
            if (!didWork && events.request && !(editorWindow && editorWindow->isVisible())) {
                if (WaitForSingleObject(events.request, 20) == WAIT_TIMEOUT)
                    juce::MessageManager::getInstance()->runDispatchLoopUntil(1);
                continue;
            }
#endif
            if ((editorWindow != nullptr && editorWindow->isVisible()) || !didWork)
                juce::MessageManager::getInstance()->runDispatchLoopUntil(1);
            else if (!didWork)
                juce::Thread::sleep(1);
        }
        editorWindow.reset();
        if (instance != nullptr)
            instance->releaseResources();
        setWorkerStatus(*shared, cydaw::plugins::SharedPluginState::stopping, "Worker stopped");
        return 0;
    } catch (const std::exception& exception) {
        setWorkerStatus(*shared, cydaw::plugins::SharedPluginState::error,
                        juce::String("Plugin exception: ") + exception.what());
        return 16;
    } catch (...) {
        setWorkerStatus(*shared, cydaw::plugins::SharedPluginState::error,
                        "Unknown plugin exception");
        return 17;
    }
}

} // namespace

int main(const int argc, char* argv[])
{
    juce::ScopedJuceInitialiser_GUI initialiseJuce;
    juce::StringArray arguments;
    for (int index = 1; index < argc; ++index)
        arguments.add(juce::String::fromUTF8(argv[index]));

    if (arguments.contains("--self-test") || arguments.contains("--worker-handshake"))
        return runSelfTest();

    auto realtimeIndex = arguments.indexOf("--realtime-plugin");
    if (realtimeIndex < 0)
        realtimeIndex = arguments.indexOf("--realtime-vst3");
    const auto passthrough = arguments.contains("--realtime-passthrough");
    if ((realtimeIndex >= 0 && realtimeIndex + 1 < arguments.size()) || passthrough) {
        const auto pluginFile = passthrough ? juce::File {} : juce::File(arguments[realtimeIndex + 1]);
        const auto sharedFile = juce::File(argumentValue(arguments, "--shared-file"));
        const auto sampleRate = argumentValue(arguments, "--sample-rate", "48000").getDoubleValue();
        const auto maximumBlockSize = argumentValue(arguments, "--block-size", "512").getIntValue();
        const auto channels = argumentValue(arguments, "--channels", "2").getIntValue();
        return runRealtimeWorker(pluginFile, sharedFile, sampleRate, maximumBlockSize,
                                 channels, passthrough, argumentValue(arguments, "--parent-pid", "0").getIntValue());
    }

    auto probeIndex = arguments.indexOf("--probe-plugin");
    if (probeIndex < 0)
        probeIndex = arguments.indexOf("--probe-vst3");
    if (probeIndex >= 0 && probeIndex + 1 < arguments.size()) {
        juce::File outputFile;
        const auto outputIndex = arguments.indexOf("--output");
        if (outputIndex >= 0 && outputIndex + 1 < arguments.size())
            outputFile = juce::File(arguments[outputIndex + 1]);
        return probePlugin(juce::File(arguments[probeIndex + 1]), outputFile, false);
    }

    auto validateIndex = arguments.indexOf("--validate-plugin");
    if (validateIndex < 0)
        validateIndex = arguments.indexOf("--validate-vst3");
    if (validateIndex >= 0 && validateIndex + 1 < arguments.size()) {
        juce::File outputFile;
        const auto outputIndex = arguments.indexOf("--output");
        if (outputIndex >= 0 && outputIndex + 1 < arguments.size())
            outputFile = juce::File(arguments[outputIndex + 1]);
        return probePlugin(juce::File(arguments[validateIndex + 1]), outputFile, true);
    }

    std::cerr << "Usage: AudioStudioPluginWorker --self-test | --probe-plugin <plugin> | "
                 "--validate-plugin <plugin> [--output file.json] | "
                 "--realtime-plugin <plugin> --shared-file <path>\n";
    return 2;
}
