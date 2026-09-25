#define UNICODE
#define _UNICODE
#include <windows.h>
#include <string>
int WINAPI wWinMain(HINSTANCE, HINSTANCE, PWSTR arguments, int) {
    wchar_t path[32768]; GetModuleFileNameW(nullptr, path, 32768);
    std::wstring root(path); root.resize(root.find_last_of(L"\\/"));
    // venv layout (runtime\python\Scripts\pythonw.exe) or portable layout (runtime\python\pythonw.exe)
    std::wstring python = root + L"\\runtime\\python\\Scripts\\pythonw.exe";
    if (GetFileAttributesW(python.c_str()) == INVALID_FILE_ATTRIBUTES) python = root + L"\\runtime\\python\\pythonw.exe";
    std::wstring command = L"\"" + python + L"\" \"" + root + L"\\app\\desktop.py\" " + arguments;
    STARTUPINFOW startup{}; startup.cb = sizeof(startup); PROCESS_INFORMATION process{};
    if (!CreateProcessW(python.c_str(), command.data(), nullptr, nullptr, FALSE, 0, nullptr, root.c_str(), &startup, &process)) {
        MessageBoxW(nullptr, L"Runtime manquant ou lancement impossible. Consulter LISEZ-MOI.md.", L"CyTools_AudioStudio", MB_ICONERROR); return 1;
    }
    CloseHandle(process.hThread); CloseHandle(process.hProcess); return 0;
}
