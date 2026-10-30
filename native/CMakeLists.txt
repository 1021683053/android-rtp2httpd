cmake_minimum_required(VERSION 3.22)
project(android_rtp2httpd LANGUAGES C)

if(NOT ANDROID OR NOT ANDROID_ABI STREQUAL "arm64-v8a")
  message(FATAL_ERROR "Use the Android NDK toolchain and arm64-v8a ABI")
endif()
if(NOT DEFINED RTP2HTTPD_SOURCE_DIR)
  message(FATAL_ERROR "RTP2HTTPD_SOURCE_DIR must name the prepared upstream source")
endif()

add_subdirectory("${RTP2HTTPD_SOURCE_DIR}" upstream)
target_sources(rtp2httpd PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}/android_entry.c")
target_compile_options(rtp2httpd PRIVATE -ffunction-sections -fdata-sections)
target_link_options(rtp2httpd PRIVATE
  -pie -Wl,--gc-sections -Wl,-z,relro,-z,now
  -Wl,-z,max-page-size=16384 -Wl,-z,common-page-size=16384)
set_target_properties(rtp2httpd PROPERTIES
  POSITION_INDEPENDENT_CODE ON
  RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/bin")
