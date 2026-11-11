#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <shellapi.h>
#include <stdio.h>
#include <stdlib.h>
#include <wchar.h>
#include <string>

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

int main(int /*argc*/, char* /*argv*/[]) {
    int wargc = 0;
    LPWSTR* wargv = CommandLineToArgvW(GetCommandLineW(), &wargc);
    if (wargv) {
        for (int i = 1; i < wargc; ++i) {
            if (wcscmp(wargv[i], L"--self-test") == 0 || wcscmp(wargv[i], L"--version") == 0) {
                wprintf(L"Scash P2Pool QtKawaii Launcher v0.2.0-beta.5 (Publisher: magicalgirlsunite)\n");
                LocalFree(wargv);
                return 0;
            }
        }
    }

    SetConsoleTitleW(L"Scash P2Pool - peer2peer-pool (QtKawaii Edition v0.2.0-beta.5)");

    HANDLE hOut = GetStdHandle(STD_OUTPUT_HANDLE);
    if (hOut != NULL && hOut != INVALID_HANDLE_VALUE) {
        DWORD dwMode = 0;
        if (GetConsoleMode(hOut, &dwMode)) {
            SetConsoleMode(hOut, dwMode | ENABLE_VIRTUAL_TERMINAL_PROCESSING);
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

    wchar_t exe_path[32768];
    DWORD len = GetModuleFileNameW(NULL, exe_path, 32768);
    if (len == 0 || len >= 32768) {
        fwprintf(stderr, L"[ERROR] Could not resolve launcher executable path.\n");
        if (wargv) LocalFree(wargv);
        return 1;
    }

    std::wstring base_dir(exe_path);
    size_t slash = base_dir.find_last_of(L"\\/");
    if (slash != std::wstring::npos) {
        base_dir = base_dir.substr(0, slash);
    }
    SetCurrentDirectoryW(base_dir.c_str());

    std::wstring bundled_pypy = base_dir + L"\\runtime\\pypy2\\pypy.exe";
    std::wstring script_path = base_dir + L"\\start_scash_p2pool.py";

    if (!file_exists_w(script_path)) {
        fwprintf(stderr, L"[ERROR] Missing start_scash_p2pool.py in: %ls\n", base_dir.c_str());
        wprintf(L"\nPress Enter to close...");
        getwchar();
        if (wargv) LocalFree(wargv);
        return 1;
    }

    std::wstring cmd;
    if (file_exists_w(bundled_pypy)) {
        cmd = L"\"" + bundled_pypy + L"\" \"" + script_path + L"\"";
    } else {
        cmd = L"python \"" + script_path + L"\"";
    }

    if (wargv) {
        for (int i = 1; i < wargc; ++i) {
            cmd += L" \"";
            cmd += wargv[i];
            cmd += L"\"";
        }
        LocalFree(wargv);
        wargv = NULL;
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
