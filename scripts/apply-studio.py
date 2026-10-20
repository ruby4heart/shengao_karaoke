"""Apply the studio adaptation only to the private Aegisub development copy."""
from pathlib import Path
import json
import re
import shutil

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'vendor'/'aegisub'


def replace(relative,old,new):
    path=SOURCE/relative
    text=path.read_text(encoding='utf-8-sig')
    if new in text:
        return
    if old not in text:
        raise RuntimeError(f'Expected source fragment missing: {relative}')
    path.write_text(text.replace(old,new),encoding='utf-8')

def copy_changed(source,target):
    if not target.exists() or source.read_bytes()!=target.read_bytes():
        shutil.copyfile(source,target)


def add_include(relative,header,after):
    path=SOURCE/relative
    text=path.read_text(encoding='utf-8-sig')
    lines=text.splitlines()
    if lines.count(header)==1:
        return
    lines=[line for line in lines if line!=header]
    anchor=lines.index(after)
    lines.insert(anchor+1,header)
    path.write_text('\n'.join(lines)+'\n',encoding='utf-8')


for name in ('studio_panel.h','studio_panel.cpp','studio_audio_provider.h','studio_document.h','studio_integration.cpp','studio_workflow.h','studio_workspace.cpp','studio_tasks.cpp','studio_shell.h','studio_shell.cpp','studio_theme.h','studio_audio_theme.h','studio_editing.h','studio_review.inc','studio_karaoke.h','studio_karaoke_display.inc'):
    copy_changed(ROOT/'native'/name,SOURCE/'src'/name)
copy_changed(ROOT/'native/studio_timing_drag.inc',SOURCE/'src/studio_timing_drag.inc')
copy_changed(ROOT/'native/studio_correction.cpp',SOURCE/'src/studio_correction.cpp')
copy_changed(ROOT/'native/studio_calibration.h',SOURCE/'src/studio_calibration.h')
copy_changed(ROOT/'native/studio_correction_test.inc',SOURCE/'src/studio_correction_test.inc')
copy_changed(ROOT/'native/studio_pauses.h',SOURCE/'src/studio_pauses.h')
copy_changed(ROOT/'native/studio_usability.cpp',SOURCE/'src/studio_usability.cpp')
copy_changed(ROOT/'native/studio_usability_test.inc',SOURCE/'src/studio_usability_test.inc')
copy_changed(ROOT/'native'/'studio_audio_test.cpp',SOURCE/'tests'/'tests'/'studio_audio_test.cpp')
copy_changed(ROOT/'native'/'studio_document_test.cpp',SOURCE/'tests'/'tests'/'studio_document_test.cpp')
copy_changed(ROOT/'native'/'studio_workflow_test.cpp',SOURCE/'tests'/'tests'/'studio_workflow_test.cpp')
copy_changed(ROOT/'native'/'source_version.h',SOURCE/'tools'/'source_version.h')
replace('tools/version.ps1','throw "$repositoryRootPath is not a git repository"',
'''if ([string]::IsNullOrWhiteSpace($BuildRoot)) { $BuildRoot = Join-Path $repositoryRootPath 'build' }
  New-Item -ItemType Directory -Path $BuildRoot -Force | Out-Null
  Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'source_version.h') -Destination (Join-Path $BuildRoot 'git_version.h') -Force
  exit 0''')
replace('tests/meson.build',"    'tests/audio.cpp',", "    'tests/audio.cpp',\n    'tests/studio_audio_test.cpp',")
replace('tests/meson.build',"    'tests/studio_audio_test.cpp',", "    'tests/studio_audio_test.cpp',\n    'tests/studio_document_test.cpp',")
replace('tests/meson.build',"    'tests/studio_document_test.cpp',", "    'tests/studio_document_test.cpp',\n    'tests/studio_workflow_test.cpp',")
replace('tests/meson.build','include_directories: [tests_inc, libaegisub_inc],',
        "include_directories: [tests_inc, libaegisub_inc, include_directories('../src')],")
replace('subprojects/ffmpeg/meson.build',
        "if test_libass_dep.found() and cc.has_header('iconv.h', dependencies: test_libass_dep) and host_system == 'windows'",
        "if test_libass_dep.found() and test_libass_dep.type_name() != 'internal' and cc.has_header('iconv.h', dependencies: test_libass_dep) and host_system == 'windows'")
add_include('src/frame_main.cpp','#include "studio_panel.h"','#include "frame_main.h"')
replace('src/frame_main.cpp','SetSize(FromDIP(wxSize(920, 700)));','SetSize(FromDIP(wxSize(1500, 950)));')
add_include('src/frame_main.cpp','#include <wx/splitter.h>','#include "studio_panel.h"')
frame=SOURCE/'src/frame_main.cpp'
text=frame.read_text(encoding='utf-8')
if '// Shengao three-pane workspace' not in text:
    start=text.index('void FrameMain::InitContents() {')
    end=text.index('void FrameMain::SetDisplayMode(',start)
    text=text[:start]+'''void FrameMain::InitContents() {
    // Shengao three-pane workspace: lyrics | video/audio/timing | readings/API.
    auto Panel = new wxPanel(this, -1, wxDefaultPosition, wxDefaultSize, wxTAB_TRAVERSAL | wxCLIP_CHILDREN);
    auto split = new wxSplitterWindow(Panel, wxID_ANY, wxDefaultPosition, wxDefaultSize, wxSP_LIVE_UPDATE);
    auto lyrics = new wxPanel(split);
    auto editing = new wxPanel(split);
    context->subsGrid = new BaseGrid(lyrics, context.get());
    auto lyrics_sizer = new wxBoxSizer(wxVERTICAL);
    lyrics_sizer->Add(context->subsGrid, 1, wxEXPAND);
    lyrics->SetSizer(lyrics_sizer);
    videoBox = new VideoBox(editing, false, context.get());
    context->audioBox = audioBox = new AudioBox(editing, context.get());
    auto EditBox = new SubsEditBox(editing, context.get());
    ToolsSizer = new wxBoxSizer(wxVERTICAL);
    ToolsSizer->Add(audioBox, 0, wxEXPAND);
    ToolsSizer->Add(EditBox, 1, wxEXPAND);
    TopSizer = new wxBoxSizer(wxVERTICAL);
    TopSizer->Add(videoBox, 0, wxALIGN_CENTER_HORIZONTAL);
    TopSizer->Add(ToolsSizer, 1, wxEXPAND | wxALL, 5);
    MainSizer = new wxBoxSizer(wxVERTICAL);
    MainSizer->Add(TopSizer, 1, wxEXPAND);
    editing->SetSizer(MainSizer);
    split->SetMinimumPaneSize(240);
    split->SplitVertically(lyrics, editing, FromDIP(350));
    split->SetSashGravity(.24);
    studioPanel = new StudioPanel(Panel, context.get());
    auto workspace = new wxBoxSizer(wxHORIZONTAL);
    workspace->Add(split, 1, wxEXPAND);
    workspace->Add(studioPanel, 0, wxEXPAND | wxLEFT, 8);
    Panel->SetSizer(workspace);
    Layout();
}

'''+text[end:]
    frame.write_text(text,encoding='utf-8')
brand=frame.read_text(encoding='utf-8')
updated_brand=re.sub(r' - 声稿 Karaoke Studio \d+\.\d+(?:\.\d+)?',' - 声稿 Karaoke Studio 0.7.0',brand)
if updated_brand!=brand:frame.write_text(updated_brand,encoding='utf-8')
replace('src/frame_main.cpp','newTitle << " - Aegisub " << GetAegisubLongVersionString();','newTitle << wxString::FromUTF8(" - 声稿 Karaoke Studio 0.7.0");')
replace('src/frame_main.h','class VideoBox;','class VideoBox;\nclass StudioPanel;')
replace('src/frame_main.h','AudioBox *audioBox;', 'StudioPanel *studioPanel = nullptr;\n\tAudioBox *audioBox;')
replace('src/frame_main.cpp','void FrameMain::OnCloseWindow(wxCloseEvent &event) {',
'''void FrameMain::OnCloseWindow(wxCloseEvent &event) {
    if (studioPanel && !studioPanel->PrepareClose()) { event.Veto(); return; }''')
replace('src/audio_controller.h','std::unique_ptr<AudioPlayer> player;',
'''std::unique_ptr<agi::AudioProvider> studio_rate_provider;
    double studio_playback_rate = 1.0;
    std::unique_ptr<AudioPlayer> player;''')
replace('src/audio_controller.h','void SetVolume(double volume);',
'''void SetVolume(double volume);
    void SetPlaybackRate(double rate);''')
replace('src/audio_controller.cpp','#include "audio_controller.h"',
'''#include "audio_controller.h"
#include "studio_audio_provider.h"''')
replace('src/audio_controller.cpp','player = AudioPlayerFactory::GetAudioPlayer(provider, context->parent);',
'''studio_rate_provider = std::make_unique<StudioRateProvider>(provider, studio_playback_rate);
        player = AudioPlayerFactory::GetAudioPlayer(studio_rate_provider.get(), context->parent);''')
replace('src/audio_controller.cpp','void AudioController::OnAudioProvider(agi::AudioProvider *new_provider)',
'''void AudioController::SetPlaybackRate(double rate) {
    if (rate < .5 || rate > 1.5) return;
    studio_playback_rate = rate;
    OnAudioPlayerChanged();
}

void AudioController::OnAudioProvider(agi::AudioProvider *new_provider)''')
replace('src/main.cpp','SetAppName("Aegisub");','SetAppName("ShengaoKaraoke");')
replace('src/main.cpp','SetAppName("aegisub");','SetAppName("shengao-karaoke");')
replace('libaegisub/windows/path_win.cpp','/"Aegisub"','/"ShengaoKaraoke"')
replace('meson.build',"executable('aegisub',", "executable('shengao-karaoke',")
replace('meson.build',"cxx = meson.get_compiler('cpp')", "cxx = meson.get_compiler('cpp')\nif host_machine.system() == 'windows'\n    add_project_arguments('/utf-8', language: ['c', 'cpp'])\nendif")
config=SOURCE/'src/libresrc/default_config.json'
value=json.loads(config.read_text(encoding='utf-8'))
value['App']['Language']='zh_CN'
value['App']['Auto']['Check For Updates']=False
value['App']['Auto']['Save Every Seconds']=30
value['Subtitle']['Grid']['Column']=[{'bool':visible} for visible in
    (True,False,True,True,False,False,False,False,False,False,False,True)]
value['Subtitle']['Grid']['Hide Overrides']=2
serialized=json.dumps(value,ensure_ascii=False,indent=2)
if config.read_text(encoding='utf-8')!=serialized:
    config.write_text(serialized,encoding='utf-8')
replace('src/include/aegisub/context.h','class AudioKaraoke;', 'class AudioKaraoke;\nclass StudioPanel;')
replace('src/include/aegisub/context.h','AudioKaraoke *karaoke = nullptr;', 'AudioKaraoke *karaoke = nullptr;\n    StudioPanel *studioPanel = nullptr;')
replace('src/frame_main.cpp','studioPanel = new StudioPanel(Panel, context.get());', 'context->studioPanel = studioPanel = new StudioPanel(Panel, context.get());')
replace('src/frame_main.cpp','context->subsGrid = new BaseGrid(lyrics, context.get());',
'''auto columns=OPT_GET("Subtitle/Grid/Column")->GetListBool();
    if(columns.size()==1 && columns.front())
        OPT_SET("Subtitle/Grid/Column")->SetListBool({true,false,true,true,false,false,false,false,false,false,false,true});
    context->subsGrid = new BaseGrid(lyrics, context.get());''')
if 'new StudioShell' not in frame.read_text(encoding='utf-8'):
    replace('src/frame_main.cpp','split->SetSashGravity(.24);',
    '''split->SetSashGravity(0.0);
    CallAfter([this,split]{split->SetSashPosition(FromDIP(350));split->SetSashGravity(.24);});''')
replace('src/command/subtitle.cpp','#include "../subs_controller.h"','#include "../subs_controller.h"\n#include "../studio_panel.h"')
replace('src/command/subtitle.cpp','static void save_subtitles(agi::Context *c, agi::fs::path filename) {',
'''static void save_subtitles(agi::Context *c, agi::fs::path filename) {
    if(c->studioPanel && !c->studioPanel->FlushChanges())return;''')
replace('src/command/subtitle.cpp','return c->subsController->IsModified();',
        'return c->subsController->IsModified() || (c->studioPanel && c->studioPanel->HasPendingChanges());')
replace('src/subs_controller.cpp','#include "subs_controller.h"','#include "subs_controller.h"\n#include "studio_panel.h"')
replace('src/subs_controller.cpp','int SubsController::TryToClose(bool allow_cancel) const {',
'''int SubsController::TryToClose(bool allow_cancel) const {
    if(context->studioPanel && !context->studioPanel->FlushChanges())return wxCANCEL;''')
# Explicit offline integration command. It uses a hidden instance and its own
# marked fixture directory; ordinary launches keep the same application path.
replace('src/frame_main.h','\tFrameMain();','\texplicit FrameMain(bool show = true);')
replace('src/frame_main.h','~explicit FrameMain(bool show = true);','~FrameMain();')
replace('src/frame_main.cpp','FrameMain::FrameMain()','FrameMain::FrameMain(bool show)')
replace('src/frame_main.cpp','if (OPT_GET("App/Maximized")->GetBool()) Maximize(true);','if (show && OPT_GET("App/Maximized")->GetBool()) Maximize(true);')
replace('src/frame_main.cpp','\tShow();\n\tSetDisplayMode(1, 1);','\tif (show) Show();\n\tSetDisplayMode(1, 1);')
replace('src/main.h','agi::Context& NewProjectContext();','agi::Context& NewProjectContext(bool show = true);')
replace('src/main.cpp','agi::Context& AegisubApp::NewProjectContext() {','agi::Context& AegisubApp::NewProjectContext(bool show) {')
replace('src/main.cpp','auto frame = new FrameMain;','auto frame = new FrameMain(show);')
replace('src/main.cpp','#include "main.h"','#include "main.h"\n#include "studio_panel.h"\n#include <filesystem>')
replace('src/main.cpp','\tconfig::path = new agi::Path;', '''\tconfig::path = new agi::Path;
    auto const& studio_args = argv.GetArguments();
    bool studio_test = studio_args.size()==3 && studio_args[1]=="--studio-self-test";
    std::filesystem::path studio_fixture;
    if(studio_test) {
        studio_fixture=std::filesystem::absolute(std::filesystem::path(studio_args[2].ToStdWstring()));
        if(!std::filesystem::is_regular_file(studio_fixture/".studio-test-fixture"))return false;
        config::path->SetToken("?user",agi::fs::path(studio_fixture.wstring()));
        config::path->SetToken("?local",agi::fs::path(studio_fixture.wstring()));
    }''')
replace('src/main.cpp','\t\tNewProjectContext();','''        auto& studio_context=NewProjectContext(!studio_test);
        if(studio_test) {
            auto test_context=&studio_context;
            CallAfter([this,test_context,studio_fixture]{
                test_context->studioPanel->RunIntegrationTests(studio_fixture);
                ExitMainLoop();
            });
        }''')
replace('src/main.cpp','if (args.size() > 1)\n\t\t\tOpenFiles','if (!studio_test && args.size() > 1)\n\t\t\tOpenFiles')

# The Meson FFmpeg port probes this Win32 function without its required
# headers under MSVC. Our target is desktop Windows, where it is available.
# Keep FFmpeg's existing wide-command-line conversion active for CJK paths.
replace('subprojects/ffmpeg/fftools/cmdutils.c',
        '#if HAVE_COMMANDLINETOARGVW && defined(_WIN32)',
        '#if defined(_WIN32) && !HAVE_UWP /* Shengao desktop Unicode argv */')

replace('src/frame_main.cpp','agi::dispatch::Main().Async([=, this] { context->project->LoadList(files); });',
'''agi::dispatch::Main().Async([context=context,files=std::move(files)] {
            try {
                std::vector<agi::fs::path> ordinary;
                for(auto const& file:files)if(!context->studioPanel->OpenStudioFile(file))ordinary.push_back(file);
                if(!ordinary.empty())context->project->LoadList(ordinary);
            }catch(std::exception const& error){wxMessageBox(wxString::FromUTF8(error.what()),wxString::FromUTF8("无法打开文件"),wxOK|wxICON_ERROR,context->parent);}
        });''')
add_include('src/frame_main.cpp','#include <wx/stattext.h>','#include <wx/splitter.h>')
frame_text=frame.read_text(encoding='utf-8')
frame_start=frame_text.index('void FrameMain::InitContents() {')
frame_end=frame_text.index('void FrameMain::SetDisplayMode(',frame_start)
workspace_source=(ROOT/'native/studio_frame.inc').read_text(encoding='utf-8')
workspace_source=workspace_source[workspace_source.index('void FrameMain::InitContents() {'):].rstrip()+'\n\n'
updated_frame=frame_text[:frame_start]+workspace_source+frame_text[frame_end:]
if updated_frame!=frame_text:frame.write_text(updated_frame,encoding='utf-8')
replace('src/include/aegisub/context.h','class StudioPanel;', 'class StudioPanel;\nclass StudioShell;')
replace('src/include/aegisub/context.h','StudioPanel *studioPanel = nullptr;', 'StudioPanel *studioPanel = nullptr;\n    StudioShell *studioShell = nullptr;')
add_include('src/frame_main.cpp','#include "studio_shell.h"','#include "studio_panel.h"')
add_include('src/frame_main.cpp','#include <wx/button.h>','#include "studio_shell.h"')
add_include('src/frame_main.cpp','#include <dwmapi.h>','#include <wx/button.h>')
replace('src/frame_main.h','~FrameMain();','''~FrameMain();
#ifdef __WXMSW__
    WXLRESULT MSWWindowProc(WXUINT message,WXWPARAM wParam,WXLPARAM lParam) override;
#endif''')
replace('src/frame_main.cpp',': wxFrame(nullptr, -1, "")',': wxFrame(nullptr, -1, "",wxDefaultPosition,wxDefaultSize,wxRESIZE_BORDER|wxSYSTEM_MENU|wxMINIMIZE_BOX|wxMAXIMIZE_BOX|wxCLOSE_BOX|wxCLIP_CHILDREN)')
replace('src/frame_main.cpp','SetSize(FromDIP(wxSize(1500, 950)));','SetSize(FromDIP(wxSize(1500, 950)));\n    SetMinSize(FromDIP(wxSize(1200,720)));')
replace('src/frame_main.cpp','EnableToolBar(*OPT_GET("App/Show Toolbar"));','// Studio shell owns the visible toolbar.')
replace('src/frame_main.cpp','menu::GetMenuBar("main", this, (wxID_HIGHEST + 1) + 10000, context.get());','// Advanced native commands remain in the Studio tools popup.')
replace('src/frame_main.cpp','if (opt.GetBool()) {\n\t\tif (!GetToolBar())','if (false) { // Studio shell toolbar\n\t\tif (!GetToolBar())')
replace('src/audio_box.cpp','wxSW_3D | wxCLIP_CHILDREN','wxBORDER_NONE | wxCLIP_CHILDREN')
replace('src/audio_box.cpp','wxTAB_TRAVERSAL | wxBORDER_RAISED','wxTAB_TRAVERSAL | wxBORDER_NONE')
replace('src/audio_box.cpp','SetMinSize(wxSize(-1, OPT_GET("Audio/Display Height")->GetInt()));','SetMinSize(wxSize(0, OPT_GET("Audio/Display Height")->GetInt()));')
replace('src/audio_box.cpp','SetMinSize(wxSize(-1, new_height));','SetMinSize(wxSize(0, new_height));')
replace('src/audio_box.cpp','MainSizer->Add(toolbar::GetToolbar(panel, "audio", context, "Audio"),0,wxEXPAND|wxLEFT|wxRIGHT,3);','// Common playback and display controls live in the Studio transport.')
replace('src/video_box.cpp','topSizer->Add(toolbarSizer, 0, wxEXPAND);','visualToolBar->Hide();visualSubToolBar->Hide(); // Studio: advanced commands in Tools')
replace('src/video_box.cpp','videoBottomSizer->Add(mainToolbar, wxSizerFlags(0).Center());','mainToolbar->Hide(); // Studio transport owns playback')
replace('src/video_box.cpp','videoBottomSizer->Add(VideoSubsPos, wxSizerFlags(1).Center().Border(wxLEFT));','VideoSubsPos->Hide();')
replace('src/video_box.cpp','videoBottomSizer->Add(VideoPosition, wxSizerFlags(1).Center().Border(wxLEFT));','VideoPosition->Hide(); // Studio transport displays playback time')
replace('src/video_box.cpp','videoBottomSizer->Add(zoomBox, wxSizerFlags(0).Center().Border(wxLEFT | wxRIGHT));','zoomBox->Hide(); // Preview fits its workspace')
replace('src/video_box.cpp','SetSizer(VideoSizer);','SetSizer(VideoSizer);\n    SetBackgroundColour(wxColour(20,29,46));')
replace('src/audio_box.cpp','SetSashVisible(wxSASH_BOTTOM, true);','SetBackgroundColour(*wxWHITE);panel->SetBackgroundColour(*wxWHITE);\n    SetSashVisible(wxSASH_BOTTOM, true);')
replace('src/audio_display.cpp','wxWANTS_CHARS|wxBORDER_SIMPLE','wxWANTS_CHARS|wxBORDER_NONE')
replace('src/frame_main.cpp','hotkey::check("Main Frame", context.get(), event);','''if(dynamic_cast<StudioButton*>(wxWindow::FindFocus()) &&
       (event.GetKeyCode()==WXK_SPACE || event.GetKeyCode()==WXK_RETURN || event.GetKeyCode()==WXK_NUMPAD_ENTER)) {event.Skip();return;}
    hotkey::check("Main Frame", context.get(), event);''')
replace('src/video_box.cpp','topSizer->Add(videoDisplay, isDetached, isDetached ? wxEXPAND : 0);','if(!isDetached)topSizer->AddStretchSpacer();\n    topSizer->Add(videoDisplay, isDetached, isDetached ? wxEXPAND : 0);\n    if(!isDetached)topSizer->AddStretchSpacer();')
replace('src/res/res.rc','VALUE "CompanyName",      "Aegisub"','VALUE "CompanyName",      "Shengao Karaoke Studio contributors"')
replace('src/res/res.rc','VALUE "FileDescription",  "Aegisub subtitle editor"','VALUE "FileDescription",  "Shengao Karaoke Studio (based on Aegisub 3.5.0)"')
replace('src/res/res.rc','VALUE "InternalName",     "aegisub"','VALUE "InternalName",     "shengao-karaoke"')
replace('src/res/res.rc','VALUE "OriginalFilename", "aegisub.exe"','VALUE "OriginalFilename", "shengao-karaoke.exe"')
replace('src/res/res.rc','VALUE "ProductName",      "Aegisub"','VALUE "ProductName",      "Shengao Karaoke Studio"')
# The public Studio audio bridge is canonicalized below.
replace('src/audio_display.h','class AudioController;','class AudioController;\nclass wxMemoryDC;')
replace('src/audio_display.h','~AudioDisplay();','~AudioDisplay();\n    void StudioRender(wxMemoryDC& dc);')
replace('src/audio_display.cpp','void AudioDisplay::OnPaint(wxPaintEvent&)', '''// Same native renderer used by the window, exposed for offline verification.
void AudioDisplay::StudioRender(wxMemoryDC& dc) {
    if (!audio_renderer_provider || !provider) return;
    auto bounds=GetClientRect();
    TimeRange range(std::max(0,TimeFromRelativeX(-foot_size)),std::max(0,TimeFromRelativeX(bounds.width+foot_size)));
    PaintAudio(dc,range,bounds);
    {wxGCDC graphics(dc);PaintMarkers(graphics,range);}
    PaintLabels(dc,range);
    if(track_cursor_pos>=0)PaintTrackCursor(dc);
    scrollbar->Paint(dc,HasFocus(),audio_load_position);timeline->Paint(dc);
}

void AudioDisplay::OnPaint(wxPaintEvent&)''')
replace('src/audio_karaoke.h','~AudioKaraoke();','~AudioKaraoke();\n    void StudioRender(wxDC& dc);\n    wxWindow *StudioSplitArea() const { return split_area; }')
replace('src/audio_karaoke.cpp','''void AudioKaraoke::OnPaint(wxPaintEvent &) {
\tint w, h;
\tsplit_area->GetClientSize(&w, &h);

\twxPaintDC dc(split_area);''','''void AudioKaraoke::OnPaint(wxPaintEvent &) {
    wxPaintDC dc(split_area);StudioRender(dc);
}
void AudioKaraoke::StudioRender(wxDC& dc) {
    int w,h;split_area->GetClientSize(&w,&h);''')
add_include('src/audio_karaoke.cpp','#include "studio_karaoke.h"','#include "audio_karaoke.h"')
replace('src/audio_karaoke.cpp','cancel_button->SetToolTip(_("Discard all uncommitted splits"));',
        'cancel_button->SetToolTip(_("Discard all uncommitted splits"));\n    cancel_button->SetName("karaoke-cancel");')
replace('src/audio_karaoke.cpp','accept_button->SetToolTip(_("Commit splits"));',
        'accept_button->SetToolTip(_("Commit splits"));\n    accept_button->SetName("karaoke-accept");')
replace('src/audio_karaoke.h','std::vector<size_t> char_to_byte;',
        'std::vector<size_t> char_to_byte;\n    std::vector<size_t> studio_char_syllables;\n    std::vector<size_t> studio_syl_indices;')
replace('src/audio_karaoke.h','std::vector<size_t> studio_syl_indices;',
        'std::vector<size_t> studio_syl_indices;\n    std::vector<int> studio_char_edges;\n    int studio_text_width=0;')
replace('src/audio_karaoke.h','int studio_text_width=0;','int studio_text_width=0;\n    bool studio_furigana=false;')
replace('src/audio_karaoke.cpp','split_area->Bind(wxEVT_LEFT_DOWN, &AudioKaraoke::OnMouse, this);',
        'split_area->Bind(wxEVT_LEFT_DOWN, &AudioKaraoke::OnMouse, this);\n    split_area->Bind(wxEVT_LEFT_DCLICK, &AudioKaraoke::OnMouse, this);')
add_include('src/audio_timing_karaoke.cpp','#include "studio_karaoke.h"','#include "ass_karaoke.h"')
replace('src/audio_timing_karaoke.cpp','labels.push_back(AudioLabel{to_wx(it->text), TimeRange(it->start_time, it->start_time + it->duration)});',
        'labels.push_back(AudioLabel{it->text.empty()?wxString(it->duration>=150?L"停顿":L"短空隙"):to_wx(studio_karaoke::display_text(it->text)), TimeRange(it->start_time, it->start_time + it->duration)});')
replace('src/audio_karaoke.cpp','int line_width = spaced_text.size() * char_width + 5;',
        'int line_width = studio_text_width + 5;')
replace('src/audio_karaoke.h','wxWindow *StudioSplitArea() const { return split_area; }',
        'wxWindow *StudioSplitArea() const { return split_area; }\n    std::vector<int> const& StudioSplitLines() const { return syl_lines; }\n    std::string StudioPendingText() const;')
replace('src/audio_karaoke.h','std::string StudioPendingText() const;',
        'std::string StudioPendingText() const;\n    wxString StudioDisplayText() const { wxString value;for(auto const& text:spaced_text)value+=text;return value; }')
split_source=SOURCE/'src/audio_karaoke.cpp'
split_text=split_source.read_text(encoding='utf-8-sig')
if '#include "studio_karaoke_display.inc"' not in split_text:
    split_text,count=re.subn(r'void AudioKaraoke::OnMouse\(wxMouseEvent &event\) \{.*?(?=\nvoid AudioKaraoke::OnScrollTimer\(\))','',split_text,flags=re.S)
    if count!=1:raise RuntimeError('Expected original karaoke mouse handler')
    split_text,count=re.subn(r'void AudioKaraoke::SetDisplayText\(\) \{.*?(?=\nvoid AudioKaraoke::CancelSplit\(\))',
        '#include "studio_karaoke_display.inc"\n\nstd::string AudioKaraoke::StudioPendingText() const { return kara->GetText(); }\n',split_text,flags=re.S)
    if count!=1:raise RuntimeError('Expected original karaoke display algorithm')
    split_source.write_text(split_text,encoding='utf-8')
# Draggable line endpoints and rounded marker positions in karaoke mode.
timing_source=SOURCE/'src/audio_timing_karaoke.cpp'
timing_text=timing_source.read_text(encoding='utf-8-sig')
if '#include "studio_timing_drag.inc"' not in timing_text:
    for pattern in (r'bool AudioTimingControllerKaraoke::IsNearbyMarker\(.*?(?=\ntemplate<typename Out)',
                    r'std::vector<AudioMarker\*> AudioTimingControllerKaraoke::OnLeftClick\(.*?(?=\nstd::vector<AudioMarker\*> AudioTimingControllerKaraoke::OnRightClick)',
                    r'int AudioTimingControllerKaraoke::MoveMarker\(.*?(?=\nvoid AudioTimingControllerKaraoke::AnnounceChanges)'):
        timing_text,count=re.subn(pattern,'',timing_text,flags=re.S)
        if count!=1:raise RuntimeError('Expected karaoke timing method')
    timing_text+='\n#include "studio_timing_drag.inc"\n'
    timing_source.write_text(timing_text,encoding='utf-8')
replace('src/audio_timing_karaoke.cpp','active_line->Text = kara->GetText();',
        'active_line->Start=int(start_marker);active_line->End=int(end_marker);\n\tactive_line->Text = kara->GetText();')
replace('src/audio_timing_karaoke.cpp','AssFile::COMMIT_DIAG_TEXT, commit_id, active_line',
        'AssFile::COMMIT_DIAG_TEXT|AssFile::COMMIT_DIAG_TIME, commit_id, active_line')
replace('src/audio_display.cpp','const int drag_sensitivity = int(OPT_GET("Audio/Start Drag Sensitivity")->GetInt() * ms_per_pixel);',
        'const int drag_sensitivity = std::max(1,int(std::max<int64_t>(FromDIP(9),OPT_GET("Audio/Start Drag Sensitivity")->GetInt()) * ms_per_pixel));')
replace('src/audio_display.h','static const int foot_size = 6;','static const int foot_size = 10;')
replace('src/libresrc/default_config.json','"Waveform": "Green"','"Waveform": "Icy Blue"')
replace('tools/version.ps1','$lastSvnRevision = 6962','''# Shengao release identity is independent of the imported upstream Git tag.
$studioVersion = Join-Path $PSScriptRoot 'source_version.h'
if (Test-Path -LiteralPath $studioVersion) {
  if ([string]::IsNullOrWhiteSpace($BuildRoot)) { $BuildRoot = Join-Path $PSScriptRoot '../build' }
  New-Item -ItemType Directory -Path $BuildRoot -Force | Out-Null
  $studioTarget = Join-Path $BuildRoot 'git_version.h'
  $studioText = Get-Content -LiteralPath $studioVersion -Raw
  if (!(Test-Path -LiteralPath $studioTarget) -or (Get-Content -LiteralPath $studioTarget -Raw) -cne $studioText) {
    Copy-Item -LiteralPath $studioVersion -Destination $studioTarget -Force
  }
  exit 0
}
$lastSvnRevision = 6962''')
# Modern timeline controls use the same native renderer and persisted values.
audio_header=SOURCE/'src/audio_box.h'
audio_text=audio_header.read_text(encoding='utf-8')
audio_begin=audio_text.index('\tvoid ShowKaraokeBar(bool show);')
audio_end=audio_text.index('\t/// @brief Scroll the audio display',audio_begin)
audio_updated=audio_text[:audio_begin]+'''\tvoid ShowKaraokeBar(bool show);
    AudioDisplay *StudioDisplay() const { return audioDisplay; }
    void StudioSetHorizontalZoom(int value);
    void StudioSetAmplitude(int value);
    void StudioSetVolume(int value);

'''+audio_text[audio_end:]
if audio_updated!=audio_text:audio_header.write_text(audio_updated,encoding='utf-8')
replace('src/audio_box.cpp','void AudioBox::SetHorizontalZoom(int new_zoom)','''void AudioBox::StudioSetHorizontalZoom(int value) { SetHorizontalZoom(value); }
void AudioBox::StudioSetAmplitude(int value) {
    value=std::clamp(value,0,100);VerticalZoom->SetValue(value);OPT_SET("Audio/Zoom/Vertical")->SetInt(value);
    audioDisplay->SetAmplitudeScale(pow(std::max(1,value)/50.0,3));
}
void AudioBox::StudioSetVolume(int value) {
    value=std::clamp(value,0,100);VolumeBar->SetValue(value);OPT_SET("Audio/Volume")->SetInt(value);
    controller->SetVolume(value==0?0.0:pow(value/50.0,3));
}
void AudioBox::SetHorizontalZoom(int new_zoom)''')
replace('src/audio_box.cpp','TopSizer->Add(HorizontalZoom,0,wxEXPAND,0);','HorizontalZoom->Hide(); // Studio horizontal controls')
replace('src/audio_box.cpp','TopSizer->Add(VertVolArea,0,wxEXPAND,0);','VerticalZoom->Hide();VolumeBar->Hide();link_btn->Hide();delete VertVolArea; // Studio horizontal controls')
replace('src/audio_box.cpp','controller->SetVolume(pow(mid(1, VolumeBar->GetValue(), 100) / 50.0, 3));','StudioSetVolume(OPT_GET("Audio/Volume")->GetInt()); // Restore the visible Studio volume, including mute')
add_include('src/pen.cpp','#include "studio_audio_theme.h"','#include "pen.h"')
replace('src/pen.cpp','to_wx(opt.GetColor())','to_wx(StudioAudioColour(opt.GetName(),opt.GetColor()))')
replace('src/pen.cpp','to_wx(OPT_GET(colour_opt)->GetColor())','to_wx(StudioAudioColour(colour_opt,OPT_GET(colour_opt)->GetColor()))')
replace('src/audio_colorscheme.cpp','\tfor (size_t i = 0; i <= factor; ++i)','// Shengao studio palette, only for unchanged built-in gradients.\n    if(scheme_name=="Icy Blue" && opt_base.ends_with("/Normal/") && h_base == 191.0 && h_scale == -128.0 && s_base == 127.0 && s_scale == 128.0 && l_base == 0.0 && l_scale == 255.0) {h_base=160;h_scale=-25;s_base=140;s_scale=80;l_base=14;l_scale=180;}\n    if(scheme_name=="Icy Blue" && opt_base.ends_with("/Inactive/") && h_base == 191.0 && h_scale == -128.0 && s_base == 63.0 && s_scale == 192.0 && l_base == 32.0 && l_scale == 192.0) {h_base=160;h_scale=-25;s_base=140;s_scale=80;l_base=10;l_scale=180;}\n    if(scheme_name=="Icy Blue" && opt_base.ends_with("/Selection/") && h_base == 191.0 && h_scale == -128.0 && s_base == 127.0 && s_scale == 128.0 && l_base == 32.0 && l_scale == 192.0) {h_base=160;h_scale=-25;s_base=140;s_scale=80;l_base=22;l_scale=180;}\n    if(scheme_name=="Icy Blue" && opt_base.ends_with("/Primary/") && h_base == 191.0 && h_scale == -128.0 && s_base == 127.0 && s_scale == 128.0 && l_base == 64.0 && l_scale == 192.0) {h_base=160;h_scale=-25;s_base=140;s_scale=80;l_base=30;l_scale=180;}\n\tfor (size_t i = 0; i <= factor; ++i)')

add_include('src/audio_display.cpp','#include "studio_audio_theme.h"','#include "audio_display.h"')
for suffix in ('Light','Dark','Selection'):
    replace('src/audio_display.cpp',f'to_wx(OPT_GET(opt_prefix + "{suffix}")->GetColor())',f'to_wx(StudioAudioColour(opt_prefix + "{suffix}",OPT_GET(opt_prefix + "{suffix}")->GetColor()))')

# Canonicalize once. Independent insertions after the same anchor used to add
# duplicate files and force a full Meson/CMake reconfigure on every build.
studio_cpp=('studio_panel.cpp','studio_correction.cpp','studio_usability.cpp','studio_integration.cpp','studio_workspace.cpp','studio_tasks.cpp','studio_shell.cpp')
source_list=SOURCE/'src/meson.build';previous=source_list.read_text(encoding='utf-8')
clean=re.sub(r"^[ \t]*'(?:"+'|'.join(re.escape(name) for name in studio_cpp)+r")',[ \t]*\n",'',previous,flags=re.M)
clean=clean.replace('aegisub_src = files(\n','aegisub_src = files(\n'+''.join("    '"+name+"',\n" for name in studio_cpp),1)
if clean!=previous:source_list.write_text(clean,encoding='utf-8')
replace('src/audio_timing.h','virtual void Commit() = 0;','virtual void Commit() = 0;\n    virtual void OnDragEnd() {}')
replace('src/audio_timing_karaoke.cpp','void Commit() override;','void Commit() override;\n    void OnDragEnd() override { Commit();commit_id=-1; }')
replace('src/audio_display.cpp','return !event.ButtonUp(button_used);',
        'if(event.ButtonUp(button_used)){timing_controller->OnDragEnd();return false;}\n\t\treturn true;')
print('Studio adaptation applied to',SOURCE)
