/* Stage Chart.exe: starts the bundled Python with the Stage Chart window.
 *
 *   <folder>\Stage Chart.exe  ->  <folder>\runtime\pythonw.exe -B -E -s "<folder>\app\gui_win.py" [args]
 *
 * Files dropped on the .exe, or sent with right-click > Send to, are passed through as arguments.
 * Build:  x86_64-w64-mingw32-gcc -O2 -municode -mwindows launcher.c launcher_res.o -o "Stage Chart.exe"
 */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <wchar.h>

static const wchar_t *skip_argv0(const wchar_t *cmd) {
    if (*cmd == L'"') {
        cmd++;
        while (*cmd && *cmd != L'"') cmd++;
        if (*cmd == L'"') cmd++;
    } else {
        while (*cmd && *cmd != L' ' && *cmd != L'\t') cmd++;
    }
    while (*cmd == L' ' || *cmd == L'\t') cmd++;
    return cmd;
}

static int exists(const wchar_t *p) {
    return GetFileAttributesW(p) != INVALID_FILE_ATTRIBUTES;
}

int WINAPI wWinMain(HINSTANCE hInst, HINSTANCE hPrev, PWSTR lpCmd, int nShow) {
    (void)hInst; (void)hPrev; (void)lpCmd; (void)nShow;
    wchar_t dir[32768], py[32768], script[32768];
    DWORD n = GetModuleFileNameW(NULL, dir, 32768);
    if (n == 0 || n >= 32768) return 1;
    wchar_t *slash = wcsrchr(dir, L'\\');
    if (slash) *slash = 0;

    _snwprintf(py, 32768, L"%ls\\runtime\\pythonw.exe", dir);
    _snwprintf(script, 32768, L"%ls\\app\\gui_win.py", dir);
    if (!exists(py) || !exists(script)) {
        MessageBoxW(NULL,
            L"Stage Chart can't find its files.\n\n"
            L"If you opened it from inside the zip file, close this, right-click \"Stage Chart.zip\", "
            L"choose \"Extract All...\", and run Stage Chart from the extracted folder.\n\n"
            L"Keep \"Stage Chart.exe\" in the same folder as its \"app\" and \"runtime\" folders.",
            L"Stage Chart", MB_ICONERROR | MB_OK);
        return 2;
    }

    const wchar_t *rest = skip_argv0(GetCommandLineW());
    size_t len = wcslen(py) + wcslen(script) + wcslen(rest) + 64;
    wchar_t *cmd = (wchar_t *)HeapAlloc(GetProcessHeap(), 0, len * sizeof(wchar_t));
    if (!cmd) return 3;
    _snwprintf(cmd, len, L"\"%ls\" -B -E -s \"%ls\" %ls", py, script, rest);

    STARTUPINFOW si;
    PROCESS_INFORMATION pi;
    ZeroMemory(&si, sizeof si);
    si.cb = sizeof si;
    ZeroMemory(&pi, sizeof pi);
    if (!CreateProcessW(py, cmd, NULL, NULL, FALSE, 0, NULL, dir, &si, &pi)) {
        wchar_t msg[512];
        _snwprintf(msg, 512, L"Stage Chart couldn't start (Windows error %lu).", GetLastError());
        MessageBoxW(NULL, msg, L"Stage Chart", MB_ICONERROR | MB_OK);
        return 4;
    }
    AllowSetForegroundWindow(pi.dwProcessId);
    CloseHandle(pi.hThread);
    CloseHandle(pi.hProcess);
    return 0;
}
