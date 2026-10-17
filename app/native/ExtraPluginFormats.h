#pragma once
#include <juce_audio_processors/juce_audio_processors.h>
namespace cydaw::plugins
{
std::unique_ptr<juce::AudioPluginFormat> extraPluginFormat(const juce::File &);
juce::var validateJsfxGraphics(juce::AudioPluginInstance &);
bool isExtraFormat(const juce::File &);
std::unique_ptr<juce::AudioPluginInstance> createExtraPlugin(const juce::File &, double, int, juce::String &,
                                                             const juce::String &id = {});
void scanExtraPlugin(const juce::File &, juce::OwnedArray<juce::PluginDescription> &, juce::String &);
} // namespace cydaw::plugins
