#pragma once
#include <atomic>
#include <juce_audio_processors/juce_audio_processors.h>
namespace cydaw::plugins
{
struct HostedControl : juce::HostedAudioProcessorParameter
{
    juce::String id, name, unit;
    double minimum{}, maximum{1}, initial{};
    int steps{};
    bool automate{true};
    std::atomic<double> value{};
    std::function<juce::String(double)> display;
    HostedControl(juce::String key, juce::String label, double lo, double hi, double def)
        : id(std::move(key)), name(std::move(label)), minimum(lo), maximum(hi), initial(def), value(def)
    {
    }
    float getValue() const override
    {
        return maximum > minimum ? float((value.load() - minimum) / (maximum - minimum)) : 0;
    }
    void setValue(float n) override
    {
        if (std::isfinite(n))
            value.store(minimum + std::clamp(double(n), 0.0, 1.0) * (maximum - minimum));
    }
    float getDefaultValue() const override
    {
        return maximum > minimum ? float((initial - minimum) / (maximum - minimum)) : 0;
    }
    juce::String getName(int n) const override
    {
        return name.substring(0, n);
    }
    juce::String getLabel() const override
    {
        return unit;
    }
    juce::String getParameterID() const override
    {
        return id;
    }
    int getNumSteps() const override
    {
        return steps > 1 ? steps : juce::AudioProcessor::getDefaultNumParameterSteps();
    }
    bool isDiscrete() const override
    {
        return steps > 1;
    }
    bool isBoolean() const override
    {
        return steps == 2;
    }
    bool isAutomatable() const override
    {
        return automate;
    }
    juce::String getText(float n, int length) const override
    {
        auto v = minimum + n * (maximum - minimum);
        return (display ? display(v) : juce::String(v, 3)).substring(0, length);
    }
    float getValueForText(const juce::String &s) const override
    {
        return maximum > minimum ? float((s.getDoubleValue() - minimum) / (maximum - minimum)) : 0;
    }
};
class HostedInstance : public juce::AudioPluginInstance
{
  public:
    juce::PluginDescription description;
    const juce::String getName() const override
    {
        return description.name;
    }
    void fillInPluginDescription(juce::PluginDescription &d) const override
    {
        d = description;
    }
    bool acceptsMidi() const override
    {
        return true;
    }
    bool producesMidi() const override
    {
        return true;
    }
    double getTailLengthSeconds() const override
    {
        return 0;
    }
    int getNumPrograms() override
    {
        return 1;
    }
    int getCurrentProgram() override
    {
        return 0;
    }
    void setCurrentProgram(int) override {}
    const juce::String getProgramName(int) override
    {
        return "Default";
    }
    void changeProgramName(int, const juce::String &) override {}
    bool hasEditor() const override
    {
        return true;
    }
    juce::AudioProcessorEditor *createEditor() override
    {
        return new juce::GenericAudioProcessorEditor(*this);
    }

  protected:
    void addPorts(int inputs, int outputs)
    {
        setPlayConfigDetails(inputs, outputs, 48000, 512);
        description.numInputChannels = inputs;
        description.numOutputChannels = outputs;
    }
};
} // namespace cydaw::plugins
