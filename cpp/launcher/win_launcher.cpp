#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <shellapi.h>
#include <shlobj.h>
#include <stdio.h>
#include <stdlib.h>
#include <wchar.h>
#include <string>
#include <vector>

#ifndef ENABLE_VIRTUAL_TERMINAL_PROCESSING
#define ENABLE_VIRTUAL_TERMINAL_PROCESSING 0x0004
#endif

static HANDLE g_hJob = NULL;
static HANDLE g_hChildProcess = NULL;

static BOOL WINAPI ConsoleCtrlHandler(DWORD dwCtrlType) {
    switch (dwCtrlType) {
        case CTRL_C_EVENT:
        case CTRL_BREAK_EVENT:
        case CTRL_CLOSE_EVENT:
        case CTRL_LOGOFF_EVENT:
        case CTRL_SHUTDOWN_EVENT:
            if (g_hChildProcess != NULL) {
                WaitForSingleObject(g_hChildProcess, 3500);
            }
            if (g_hJob != NULL) {
                HANDLE hTmp = g_hJob;
                g_hJob = NULL;
                CloseHandle(hTmp);
            }
            if (dwCtrlType == CTRL_CLOSE_EVENT || dwCtrlType == CTRL_LOGOFF_EVENT || dwCtrlType == CTRL_SHUTDOWN_EVENT) {
                ExitProcess(0);
            }
            return TRUE;
        default:
            return FALSE;
    }
}

static bool file_exists_w(const std::wstring& path) {
    DWORD attr = GetFileAttributesW(path.c_str());
    return (attr != INVALID_FILE_ATTRIBUTES) && !(attr & FILE_ATTRIBUTE_DIRECTORY);
}

static std::wstring get_env_w(const wchar_t* name) {
    wchar_t buf[32768];
    DWORD n = GetEnvironmentVariableW(name, buf, 32768);
    if (n > 0 && n < 32768) {
        return std::wstring(buf, n);
    }
    return L"";
}

int main(int /*argc*/, char* /*argv*/[]) {
    int wargc = 0;
    LPWSTR* wargv = CommandLineToArgvW(GetCommandLineW(), &wargc);
    bool skip_admin = (!get_env_w(L"GITHUB_ACTIONS").empty());
    std::vector<std::wstring> forward_args;

    if (wargv) {
        for (int i = 1; i < wargc; ++i) {
            std::wstring a(wargv[i]);
            if (a == L"--self-test" || a == L"--version") {
                wprintf(L"Scash P2Pool QtKawaii Launcher v0.2.0-beta.8 (Publisher: magicalgirlsunite, MSR+WinRing0)\n");
                LocalFree(wargv);
                return 0;
            }
            if (a == L"--no-admin" || a == L"--elevated") {
                skip_admin = true;
                continue;
            }
            if (a == L"--orig-localappdata" && (i + 1) < wargc) {
                SetEnvironmentVariableW(L"SCASH_ORIG_LOCALAPPDATA", wargv[++i]);
                continue;
            }
            if (a == L"--orig-appdata" && (i + 1) < wargc) {
                SetEnvironmentVariableW(L"SCASH_ORIG_APPDATA", wargv[++i]);
                continue;
            }
            forward_args.push_back(a);
        }
        LocalFree(wargv);
        wargv = NULL;
    }

    wchar_t exe_path[32768];
    DWORD len = GetModuleFileNameW(NULL, exe_path, 32768);
    if (len == 0 || len >= 32768) {
        fwprintf(stderr, L"[ERROR] Could not resolve launcher executable path.\n");
        return 1;
    }

    std::wstring base_dir(exe_path);
    size_t slash = base_dir.find_last_of(L"\\/");
    if (slash != std::wstring::npos) {
        base_dir = base_dir.substr(0, slash);
    }
    SetCurrentDirectoryW(base_dir.c_str());

    // Auto-elevate via Windows UAC so WinRing0x64.sys (RandomX MSR Mod) & SeLockMemoryPrivilege (HugePages) unlock full CPU hashrate!
    if (!skip_admin && !IsUserAnAdmin()) {
        std::wstring params = L"--elevated";
        std::wstring lad = get_env_w(L"LOCALAPPDATA");
        std::wstring rad = get_env_w(L"APPDATA");
        if (!lad.empty()) {
            params += L" --orig-localappdata \"" + lad + L"\"";
        }
        if (!rad.empty()) {
            params += L" --orig-appdata \"" + rad + L"\"";
        }
        for (size_t i = 0; i < forward_args.size(); ++i) {
            params += L" \"" + forward_args[i] + L"\"";
        }
        SHELLEXECUTEINFOW sei;
        ZeroMemory(&sei, sizeof(sei));
        sei.cbSize = sizeof(sei);
        sei.lpVerb = L"runas";
        sei.lpFile = exe_path;
        sei.lpParameters = params.c_str();
        sei.lpDirectory = base_dir.c_str();
        sei.nShow = SW_SHOWNORMAL;
        if (ShellExecuteExW(&sei)) {
            return 0;
        }
        wprintf(L"[Tip] Running without Administrator permission (mining still works, just at standard speed without MSR/HugePages boost).\n");
    }

    SetConsoleTitleW(L"Scash P2Pool - peer2peer-pool (QtKawaii Edition v0.2.0-beta.8)");

    HANDLE hOut = GetStdHandle(STD_OUTPUT_HANDLE);
    if (hOut != NULL && hOut != INVALID_HANDLE_VALUE) {
        DWORD dwMode = 0;
        if (GetConsoleMode(hOut, &dwMode)) {
            SetConsoleMode(hOut, dwMode | ENABLE_VIRTUAL_TERMINAL_PROCESSING);
        }
        CONSOLE_SCREEN_BUFFER_INFO csbi;
        if (GetConsoleScreenBufferInfo(hOut, &csbi)) {
            SHORT curW = csbi.srWindow.Right - csbi.srWindow.Left + 1;
            SHORT curH = csbi.srWindow.Bottom - csbi.srWindow.Top + 1;
            COORD maxWin = GetLargestConsoleWindowSize(hOut);
            SHORT wantW = (maxWin.X > 90) ? ((maxWin.X - 2 < 128) ? (maxWin.X - 2) : 128) : 128;
            SHORT wantH = (maxWin.Y > 30) ? ((maxWin.Y - 2 < 42) ? (maxWin.Y - 2) : 42) : 42;
            if (curW < 124 && wantW >= 124) {
                COORD bufSz;
                bufSz.X = (csbi.dwSize.X > wantW) ? csbi.dwSize.X : wantW;
                bufSz.Y = (csbi.dwSize.Y > 400) ? csbi.dwSize.Y : 400;
                SetConsoleScreenBufferSize(hOut, bufSz);
                SMALL_RECT winRect = {0, 0, (SHORT)(wantW - 1), (SHORT)(((curH > wantH) ? curH : wantH) - 1)};
                SetConsoleWindowInfo(hOut, TRUE, &winRect);
            }
        }
    }

    g_hJob = CreateJobObjectW(NULL, NULL);
    if (g_hJob != NULL) {
        SetHandleInformation(g_hJob, HANDLE_FLAG_INHERIT, 0);
        JOBOBJECT_EXTENDED_LIMIT_INFORMATION jeli;
        ZeroMemory(&jeli, sizeof(jeli));
        jeli.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
        SetInformationJobObject(g_hJob, JobObjectExtendedLimitInformation, &jeli, sizeof(jeli));
    }

    SetConsoleCtrlHandler(ConsoleCtrlHandler, TRUE);

    std::wstring bundled_pypy = base_dir + L"\\runtime\\pypy2\\pypy.exe";
    std::wstring script_path = base_dir + L"\\start_scash_p2pool.py";

    if (!file_exists_w(script_path)) {
        fwprintf(stderr, L"[ERROR] Missing start_scash_p2pool.py in: %ls\n", base_dir.c_str());
        wprintf(L"\nPress Enter to close...");
        getwchar();
        return 1;
    }

    std::wstring cmd;
    if (file_exists_w(bundled_pypy)) {
        cmd = L"\"" + bundled_pypy + L"\" \"" + script_path + L"\"";
    } else {
        cmd = L"python \"" + script_path + L"\"";
    }

    for (size_t i = 0; i < forward_args.size(); ++i) {
        cmd += L" \"" + forward_args[i] + L"\"";
    }

    STARTUPINFOW si;
    PROCESS_INFORMATION pi;
    ZeroMemory(&si, sizeof(si));
    si.cb = sizeof(si);
    ZeroMemory(&pi, sizeof(pi));

    std::wstring mutable_cmd = cmd;
    BOOL ok = CreateProcessW(
        NULL,
        &mutable_cmd[0],
        NULL,
        NULL,
        FALSE,
        0,
        NULL,
        base_dir.c_str(),
        &si,
        &pi
    );

    if (!ok) {
        DWORD err = GetLastError();
        fwprintf(stderr, L"[ERROR] Failed to launch P2Pool runtime (Win32 error %lu).\n", err);
        fwprintf(stderr, L"Command: %ls\n", cmd.c_str());
        fwprintf(stderr, L"Tip: You can also run Start-Scash-P2Pool-Windows.bat directly.\n");
        wprintf(L"\nPress Enter to close...");
        getwchar();
        return (int)err;
    }

    g_hChildProcess = pi.hProcess;
    if (g_hJob != NULL) {
        AssignProcessToJobObject(g_hJob, pi.hProcess);
    }

    WaitForSingleObject(pi.hProcess, INFINITE);
    DWORD exit_code = 0;
    GetExitCodeProcess(pi.hProcess, &exit_code);
    g_hChildProcess = NULL;
    CloseHandle(pi.hProcess);
    CloseHandle(pi.hThread);

    if (g_hJob != NULL) {
        HANDLE hTmp = g_hJob;
        g_hJob = NULL;
        CloseHandle(hTmp);
    }

    if (exit_code != 0) {
        fwprintf(stderr, L"\n[NOTICE] Scash P2Pool exited with status code %lu.\n", exit_code);
        wprintf(L"Press Enter to close...");
        getwchar();
    }
    return (int)exit_code;
}
