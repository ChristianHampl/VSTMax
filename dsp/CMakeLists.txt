cmake_minimum_required (VERSION 3.20)
project (aime_dsp CXX)

set (CMAKE_CXX_STANDARD 17)
set (CMAKE_CXX_STANDARD_REQUIRED ON)
if (NOT CMAKE_BUILD_TYPE AND NOT CMAKE_CONFIGURATION_TYPES)
	set (CMAKE_BUILD_TYPE Release)
endif ()

add_library (aime_dsp INTERFACE)
target_include_directories (aime_dsp INTERFACE ${CMAKE_CURRENT_SOURCE_DIR}/core)

if (MSVC)
	set (AIME_WARN /W4 /permissive-)
else ()
	set (AIME_WARN -Wall -Wextra -Wpedantic -Wshadow)
endif ()

add_executable (aime_dsp_tests tests/test_dsp.cpp)
target_link_libraries (aime_dsp_tests PRIVATE aime_dsp)
target_compile_options (aime_dsp_tests PRIVATE ${AIME_WARN})

add_executable (aime_render tools/aime_render.cpp)
target_link_libraries (aime_render PRIVATE aime_dsp)
target_compile_options (aime_render PRIVATE ${AIME_WARN})

enable_testing ()
add_test (NAME aime_dsp_tests COMMAND aime_dsp_tests)
