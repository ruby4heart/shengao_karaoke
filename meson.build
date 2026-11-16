project('shengao-engine', 'c', 'cpp', version: '0.8.0',
  meson_version: '>=1.0.0', license: 'MIT',
  subproject_dir: 'vendor/aegisub/subprojects',
  default_options: ['buildtype=release', 'default_library=static', 'c_std=c11', 'cpp_std=c++17', 'b_ndebug=true',
    'harfbuzz:icu=disabled', 'harfbuzz:utilities=disabled', 'harfbuzz:introspection=disabled', 'harfbuzz:docs=disabled'])

# Only dependency projects are reused. The Aegisub application, FrameMain and
# agi::Context are never configured or linked. wx is limited to offscreen DCs.
ass_project = subproject('libass', default_options: [
  'fontconfig=disabled', 'coretext=disabled', 'directwrite=enabled',
  'test=disabled', 'compare=disabled', 'profile=disabled', 'fuzz=disabled',
  'checkasm=disabled', 'libunibreak=disabled'])
ass_dep = ass_project.get_variable('libass_dep')

shared_library('shengao-render', 'desktop/native/renderer.c', dependencies: ass_dep, install: true)
shared_library('shengao-audio', [
  'desktop/native/audio_core.cpp', 'desktop/native/aegisub/fft.cpp', 'desktop/native/aegisub/hsl.cpp'], install: true)

# Keep the original Windows GDI/GDI+ text, ticks, feet and scrollbar pixels.
# No wx window is created; Qt owns the desktop application and editing model.
cmake = import('cmake')
wx_options = cmake.subproject_options()
wx_options.add_cmake_defines({
  'CMAKE_POLICY_VERSION_MINIMUM': '3.31', 'wxBUILD_INSTALL': false,
  'wxBUILD_PRECOMP': 'OFF', 'wxBUILD_SHARED': false, 'wxBUILD_MONOLITHIC': true,
  'wxBUILD_SAMPLES': 'OFF', 'wxBUILD_TESTS': 'OFF',
  'wxUSE_WEBVIEW': 'OFF', 'wxUSE_MEDIACTRL': 'OFF', 'wxUSE_STC': 'OFF',
  'wxUSE_RICHTEXT': 'OFF', 'wxUSE_XML': 'OFF', 'wxUSE_XRC': 'OFF',
  'wxUSE_HTML': 'OFF', 'wxUSE_AUI': 'OFF', 'wxUSE_PROPGRID': 'OFF',
  'wxUSE_HELP': 'OFF', 'wxUSE_WXHTML_HELP': 'OFF', 'wxUSE_OPENGL': 'OFF',
  'wxUSE_ARTPROVIDER_TANGO': 'OFF', 'wxUSE_ARTPROVIDER_STD': 'OFF',
  'wxUSE_SVG': 'OFF',
  'wxUSE_RIBBON': 'OFF', 'wxUSE_LIBPNG': 'OFF', 'wxUSE_LIBJPEG': 'OFF',
  'wxUSE_LIBTIFF': 'OFF', 'wxUSE_ZLIB': 'OFF', 'wxUSE_EXPAT': 'OFF',
  'CMAKE_BUILD_TYPE': 'Release'})
wx = cmake.subproject('wxWidgets', options: wx_options)
view_deps = [wx.dependency('wxmono')]
if wx.target_list().contains('wxregex')
  view_deps += wx.dependency('wxregex')
endif
cc = meson.get_compiler('cpp')
foreach lib : ['rpcrt4', 'comctl32', 'ole32', 'oleaut32', 'uuid', 'winspool', 'winmm', 'shlwapi', 'wininet', 'oleacc', 'uxtheme', 'version', 'winhttp', 'imm32', 'ws2_32']
  view_deps += cc.find_library(lib)
endforeach
shared_library('shengao-view', 'desktop/native/timeline_view.cpp', dependencies: view_deps,
  cpp_args: ['-DNOMINMAX'], install: true)
