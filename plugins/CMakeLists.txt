cmake_minimum_required (VERSION 3.25.0)

# Pfad zum offiziellen Steinberg VST3 SDK (https://github.com/steinbergmedia/vst3sdk, MIT-Lizenz seit 3.8):
#   cmake -S plugins -B build/plugins -Dvst3sdk_SOURCE_DIR=<pfad>/vst3sdk
# Alternativ wird external/vst3sdk im Repository verwendet (scripts/fetch_vst3sdk.*).
if (NOT vst3sdk_SOURCE_DIR)
	if (DEFINED ENV{VST3_SDK_ROOT})
		set (vst3sdk_SOURCE_DIR "$ENV{VST3_SDK_ROOT}")
	else ()
		set (vst3sdk_SOURCE_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../external/vst3sdk")
	endif ()
endif ()
if (NOT EXISTS "${vst3sdk_SOURCE_DIR}/pluginterfaces")
	message (FATAL_ERROR "VST3 SDK nicht gefunden unter '${vst3sdk_SOURCE_DIR}'. "
	                     "Bitte -Dvst3sdk_SOURCE_DIR=... setzen oder scripts/fetch_vst3sdk ausführen.")
endif ()

project (AIME VERSION 0.1.0 DESCRIPTION "AI Mix Engineer VST3 Plug-ins")

set (SMTG_ENABLE_VST3_PLUGIN_EXAMPLES OFF CACHE BOOL "" FORCE)
set (SMTG_ENABLE_VST3_HOSTING_EXAMPLES OFF CACHE BOOL "" FORCE) # Editor-Host bräuchte GTK unter Linux
set (SMTG_ENABLE_VSTGUI_SUPPORT OFF CACHE BOOL "" FORCE)        # Cubase zeigt den generischen Editor
set (SMTG_CREATE_PLUGIN_LINK OFF CACHE BOOL "" FORCE)           # Installation über scripts/install_*

add_subdirectory (${vst3sdk_SOURCE_DIR} ${PROJECT_BINARY_DIR}/vst3sdk)
smtg_enable_vst3_sdk ()
# Nur den offiziellen Validator aus den Hosting-Beispielen bauen; er läuft nach jedem Build automatisch
option (AIME_BUILD_VALIDATOR "Steinberg-Validator bauen und nach dem Build ausführen" ON)
if (AIME_BUILD_VALIDATOR AND NOT TARGET validator)
	add_subdirectory (${vst3sdk_SOURCE_DIR}/public.sdk/samples/vst-hosting/validator ${PROJECT_BINARY_DIR}/validator)
endif ()

if (MSVC)
	add_compile_options (/utf-8) # Quelltexte sind UTF-8 (deutsche Kommentare)
endif ()

set (AIME_DSP_DIR ${CMAKE_CURRENT_SOURCE_DIR}/../dsp/core)

smtg_add_vst3plugin (AIME
	source/version.h
	source/aime_link.h
	source/aime_link.cpp
	source/aime_plugin_desc.h
	source/aime_processor.h
	source/aime_controller.h
	source/entry.cpp
	${AIME_DSP_DIR}/aime_dsp.h
	${AIME_DSP_DIR}/aime_strips.h
	${AIME_DSP_DIR}/aime_state.h
	${AIME_DSP_DIR}/aime_params_gen.h
)
target_include_directories (AIME PRIVATE ${AIME_DSP_DIR} source)
target_compile_features (AIME PUBLIC cxx_std_17)
target_link_libraries (AIME PRIVATE sdk)
if (WIN32)
	target_link_libraries (AIME PRIVATE ws2_32)
else ()
	find_package (Threads REQUIRED)
	target_link_libraries (AIME PRIVATE Threads::Threads)
endif ()
smtg_target_configure_version_file (AIME)

# Mini-Host für Ende-zu-Ende-Tests (lädt AIME.vst3 über die SDK-Hosting-Klassen)
option (AIME_BUILD_HOST_RENDER "Mini-Host aime_host_render bauen" ON)
if (AIME_BUILD_HOST_RENDER)
	set (AIME_HOST_SOURCES
		tools/host_render.cpp
		${vst3sdk_SOURCE_DIR}/public.sdk/source/vst/hosting/plugprovider.cpp
		${vst3sdk_SOURCE_DIR}/public.sdk/source/common/memorystream.cpp
	)
	if (SMTG_LINUX)
		list (APPEND AIME_HOST_SOURCES ${vst3sdk_SOURCE_DIR}/public.sdk/source/vst/hosting/module_linux.cpp)
	elseif (SMTG_WIN)
		list (APPEND AIME_HOST_SOURCES ${vst3sdk_SOURCE_DIR}/public.sdk/source/vst/hosting/module_win32.cpp)
	elseif (SMTG_MAC)
		list (APPEND AIME_HOST_SOURCES ${vst3sdk_SOURCE_DIR}/public.sdk/source/vst/hosting/module_mac.mm)
		set_source_files_properties (${vst3sdk_SOURCE_DIR}/public.sdk/source/vst/hosting/module_mac.mm
		                             PROPERTIES COMPILE_FLAGS "-fobjc-arc")
	endif ()
	add_executable (aime_host_render ${AIME_HOST_SOURCES})
	target_include_directories (aime_host_render PRIVATE ${AIME_DSP_DIR})
	target_link_libraries (aime_host_render PRIVATE sdk_hosting)
	if (APPLE)
		find_library (COCOA_FRAMEWORK Cocoa)
		target_link_libraries (aime_host_render PRIVATE ${COCOA_FRAMEWORK})
	endif ()
	target_compile_features (aime_host_render PRIVATE cxx_std_17)
	add_dependencies (aime_host_render AIME)
endif ()

# Link-Protokoll-Testclient (ohne VST3-Abhängigkeit), genutzt von tests/test_plugin_link.py
add_executable (aime_link_client tools/link_client.cpp source/aime_link.cpp)
target_include_directories (aime_link_client PRIVATE ${AIME_DSP_DIR} source)
target_compile_features (aime_link_client PRIVATE cxx_std_17)
if (WIN32)
	target_link_libraries (aime_link_client PRIVATE ws2_32)
else ()
	target_link_libraries (aime_link_client PRIVATE Threads::Threads)
endif ()
