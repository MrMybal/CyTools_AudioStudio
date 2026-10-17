#include "ExtraPluginFormats.h"
namespace cydaw::plugins
{
std::unique_ptr<juce::AudioPluginInstance> createJsfx(const juce::File &, juce::String &);
std::unique_ptr<juce::AudioPluginInstance> createClap(const juce::File &, const juce::String &,
                                                      juce::String &);
void scanClap(const juce::File &, juce::OwnedArray<juce::PluginDescription> &, juce::String &);
bool isExtraFormat(const juce::File &file)
{
    return file.hasFileExtension("clap;jsfx") || file.getFileExtension().isEmpty();
}
std::unique_ptr<juce::AudioPluginInstance> createExtraPlugin(const juce::File &file, double, int,
                                                             juce::String &error, const juce::String &id)
{
    return file.hasFileExtension("clap") ? createClap(file, id, error) : createJsfx(file, error);
}
void scanExtraPlugin(const juce::File &file, juce::OwnedArray<juce::PluginDescription> &result,
                     juce::String &error)
{
    if (file.hasFileExtension("clap"))
    {
        scanClap(file, result, error);
        return;
    }
    auto plugin = createJsfx(file, error);
    if (plugin)
    {
        auto d = std::make_unique<juce::PluginDescription>();
        plugin->fillInPluginDescription(*d);
        result.add(std::move(d));
    }
}
class ExtraFormat final : public juce::AudioPluginFormat
{
    juce::String name_;

  public:
    explicit ExtraFormat(juce::String name) : name_(std::move(name)) {}
    juce::String getName() const override
    {
        return name_;
    }
    void findAllTypesForFile(juce::OwnedArray<juce::PluginDescription> &result,
                             const juce::String &path) override
    {
        juce::String error;
        scanExtraPlugin(juce::File(path), result, error);
        if (error.isNotEmpty())
            juce::Logger::writeToLog(error);
    }
    bool fileMightContainThisPluginType(const juce::String &path) override
    {
        return isExtraFormat(juce::File(path));
    }
    juce::String getNameOfPluginFromIdentifier(const juce::String &path) override
    {
        return juce::File(path).getFileNameWithoutExtension();
    }
    bool pluginNeedsRescanning(const juce::PluginDescription &) override
    {
        return true;
    }
    bool doesPluginStillExist(const juce::PluginDescription &d) override
    {
        return juce::File(d.fileOrIdentifier).exists();
    }
    bool canScanForPlugins() const override
    {
        return true;
    }
    bool isTrivialToScan() const override
    {
        return false;
    }
    juce::StringArray searchPathsForPlugins(const juce::FileSearchPath &paths, bool recursive, bool) override
    {
        juce::StringArray result;
        for (int i = 0; i < paths.getNumPaths(); ++i)
            for (auto f : paths[i].findChildFiles(juce::File::findFiles, recursive, "*.clap;*.jsfx"))
                result.add(f.getFullPathName());
        return result;
    }
    juce::FileSearchPath getDefaultLocationsToSearch() override
    {
        return {};
    }
    bool requiresUnblockedMessageThreadDuringCreation(const juce::PluginDescription &) const override
    {
        return false;
    }
    void createPluginInstance(const juce::PluginDescription &d, double rate, int block,
                              PluginCreationCallback callback) override
    {
        juce::String error;
        auto plugin = createExtraPlugin(juce::File(d.fileOrIdentifier), rate, block, error,
                                        d.pluginFormatName == "CLAP" ? d.descriptiveName : juce::String());
        callback(std::move(plugin), error);
    }
};
std::unique_ptr<juce::AudioPluginFormat> extraPluginFormat(const juce::File &f)
{
    return std::make_unique<ExtraFormat>(f.hasFileExtension("clap") ? "CLAP" : "JSFX");
}
} // namespace cydaw::plugins
