cmake_minimum_required(VERSION 3.15)
project(ScashP2PoolLauncher LANGUAGES CXX RC)

add_executable(Start-Scash-P2Pool
    win_launcher.cpp
    win_launcher.rc
)

target_compile_features(Start-Scash-P2Pool PRIVATE cxx_std_11)
target_link_libraries(Start-Scash-P2Pool PRIVATE shell32)

if(MSVC)
    target_link_options(Start-Scash-P2Pool PRIVATE "/MANIFESTUAC:level='asInvoker' uiAccess='false'")
endif()
