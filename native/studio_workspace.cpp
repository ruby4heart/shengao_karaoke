// Copyright (c) 2026 Shengao Karaoke Studio contributors. MIT.
#include "studio_panel.h"
#include "studio_shell.h"
#include "studio_workflow.h"
#include "studio_editing.h"
#include "studio_pauses.h"
#include "ass_dialogue.h"
#include "ass_file.h"
#include "audio_box.h"
#include "audio_controller.h"
#include "audio_karaoke.h"
#include "base_grid.h"
#include "frame_main.h"
#include "charset_detect.h"
#include "include/aegisub/context.h"
#include "project.h"
#include "selection_controller.h"
#include "text_file_reader.h"
#include "video_controller.h"
#include "time_range.h"
#include <libaegisub/audio/provider.h>
#include <wx/button.h>
#include <wx/checkbox.h>
#include <wx/collpane.h>
#include <wx/choice.h>
#include <wx/dialog.h>
#include <wx/filedlg.h>
#include <wx/gauge.h>
#include <wx/grid.h>
#include <wx/listbox.h>
#include <wx/msgdlg.h>
#include <wx/simplebook.h>
#include <wx/sizer.h>
#include <wx/spinctrl.h>
#include <wx/statline.h>
#include <wx/stattext.h>
#include <wx/textctrl.h>
#include <wx/tglbtn.h>
#include <wx/stdpaths.h>
#include <wx/tokenzr.h>
#include <libaegisub/json.h>
#include <fstream>
#include <cmath>
#include <algorithm>
#include <functional>
#include <set>

namespace {
wxColour const ink=studio_ui::ink,muted=studio_ui::muted,accent=studio_ui::accent,canvas=studio_ui::paper;
wxString show(std::string const& value){return wxString::FromUTF8(value);}
std::string field(json::Object const& value,char const *key){return studio_document::text(value,key);}
bool flag(json::Object const& value,char const *key){auto found=value.find(key);return found!=value.end()&&static_cast<json::Boolean const&>(found->second);}
wxString wrapped(wxWindow *control,wxString const& value,int limit){
    wxString result;int width=0;
    for(auto point:value){if(point=='\n'){result+='\n';width=0;continue;}
        wxString glyph(point);int next=control->GetTextExtent(glyph).GetWidth();
        if(width>0&&width+next>limit){result+='\n';width=0;}
        result+=glyph;width+=next;
    }return result;
}
}

void StudioPanel::BuildWorkspace() {
    SetMinSize(FromDIP(wxSize(430,500)));SetBackgroundColour(canvas);SetFont(studio_ui::font());
    auto root=new wxBoxSizer(wxVERTICAL);
    auto title=studio_ui::label(this,L"制作工具",13,ink,true);
    title->SetForegroundColour(ink);
    auto title_row=new wxBoxSizer(wxHORIZONTAL);title_row->Add(title,1,wxALIGN_CENTER_VERTICAL);auto help=new StudioButton(this,L"新手指南",StudioButton::Kind::Secondary,wxSize(86,30));help->SetName("beginner-guide");help->Bind(wxEVT_BUTTON,[this](wxCommandEvent&){try{BeginnerGuide();}catch(std::exception const& e){SetStatus(show(e.what()));}});title_row->Add(help,0);root->Add(title_row,0,wxEXPAND|wxLEFT|wxRIGHT|wxTOP,14);
    overview=studio_ui::label(this,L"添加媒体，开始制作你的第一行字幕",9,muted);overview->SetForegroundColour(muted);overview->Wrap(390);
    root->Add(overview,0,wxEXPAND|wxLEFT|wxRIGHT,18);
    auto navigation=new wxBoxSizer(wxHORIZONTAL);wxString labels[]={L"1  导入",L"2  校轴",L"3  注音",L"4  导出"};
    for(int i=0;i<4;++i){stages[i]=new StudioButton(this,labels[i],StudioButton::Kind::Tab,wxSize(0,36),true);
        stages[i]->SetMinSize(wxSize(0,FromDIP(36)));stages[i]->Bind(wxEVT_TOGGLEBUTTON,[this,i](wxCommandEvent&){ShowStage(i);});navigation->Add(stages[i],1,wxRIGHT,i==3?0:4);}
    root->Add(navigation,0,wxEXPAND|wxLEFT|wxRIGHT|wxTOP,14);root->Add(studio_ui::rule(this),0,wxEXPAND|wxLEFT|wxRIGHT|wxTOP|wxBOTTOM,8);
    current_label=studio_ui::label(this,L"当前未选择歌词",9.5,ink,true);current_label->SetMinSize(FromDIP(wxSize(0,24)));current_label->SetForegroundColour(ink);current_label->Wrap(390);
    root->Add(current_label,0,wxEXPAND|wxLEFT|wxRIGHT,18);
    auto row=new wxBoxSizer(wxHORIZONTAL);line_navigation=row;
    auto add_nav=[&](wxString label,std::function<void()> run){auto b=new StudioButton(this,label,StudioButton::Kind::Quiet,wxSize(0,30));b->SetMinSize(wxSize(0,-1));b->Bind(wxEVT_BUTTON,[this,run](wxCommandEvent&){try{run();}catch(std::exception const& e){wxMessageBox(show(e.what()),L"声稿",wxOK|wxICON_INFORMATION,this);}});row->Add(b,1,wxRIGHT,4);};
    add_nav(L"← 上一行",[this]{Navigate(-1);});add_nav(L"下一行 →",[this]{Navigate(1);});add_nav(L"下一待校准",[this]{Navigate(1,true);});
    root->Add(row,0,wxEXPAND|wxLEFT|wxRIGHT|wxTOP,8);
    dirty_label=studio_ui::label(this,L"已同步到工程",8.5,muted);dirty_label->SetForegroundColour(muted);root->Add(dirty_label,0,wxLEFT|wxTOP|wxBOTTOM,12);
    pages=new wxSimplebook(this,wxID_ANY);pages->SetMinSize(wxSize(0,0));
    std::array<wxWindow*,4> page{};std::array<wxBoxSizer*,4> body{};
    auto note=[&](int index,wxString text,bool heading=false){auto label=studio_ui::label(page[index],text,heading?10:9,heading?ink:muted,heading);if(heading&&body[index]->GetItemCount()>1)body[index]->Add(studio_ui::rule(page[index]),0,wxEXPAND|wxLEFT|wxRIGHT|wxTOP|wxBOTTOM,14);label->SetForegroundColour(heading?ink:muted);if(heading)label->SetFont(label->GetFont().Bold());label->SetLabel(wrapped(label,text,FromDIP(350)));label->SetMinSize(wxSize(0,-1));body[index]->Add(label,0,wxEXPAND|wxLEFT|wxRIGHT|wxBOTTOM,14);return label;};
    auto button=[&](int index,wxString label,std::function<void()> run,bool primary=false,bool worker=false){
        auto b=new StudioButton(page[index],label,primary?StudioButton::Kind::Primary:StudioButton::Kind::Secondary,wxSize(-1,38));b->SetMinSize(wxSize(0,FromDIP(38)));
        
        b->Bind(wxEVT_BUTTON,[this,run](wxCommandEvent&){try{run();}catch(std::exception const& e){wxMessageBox(show(e.what()),L"声稿",wxOK|wxICON_INFORMATION,this);}});
        body[index]->Add(b,0,wxEXPAND|wxLEFT|wxRIGHT|wxBOTTOM,14);if(worker)task_actions.push_back(b);return b;
    };
    for(int i=0;i<4;++i){auto scroll=new wxScrolledWindow(pages,wxID_ANY,wxDefaultPosition,wxDefaultSize,wxVSCROLL|wxTAB_TRAVERSAL);page[i]=scroll;scroll->SetBackgroundColour(*wxWHITE);scroll->SetFont(studio_ui::font());scroll->SetScrollRate(0,12);body[i]=new wxBoxSizer(wxVERTICAL);body[i]->AddSpacer(16);scroll->SetSizer(body[i]);pages->AddPage(scroll,labels[i]);}

    note(0,L"先添加媒体，再粘贴每行一句的歌词；然后选择联网或离线制作。");
    auto prepare=new wxBoxSizer(wxHORIZONTAL);auto add_media=new StudioButton(page[0],L"① 添加媒体",StudioButton::Kind::Secondary,wxSize(0,38));add_media->SetName("import-add-media");add_media->SetMinSize(FromDIP(wxSize(0,38)));add_media->Bind(wxEVT_BUTTON,[this](wxCommandEvent&){try{OpenMedia();}catch(std::exception const& e){SetStatus(show(e.what()));}});prepare->Add(add_media,1,wxRIGHT,6);auto paste=new StudioButton(page[0],L"② 粘贴歌词",StudioButton::Kind::Secondary,wxSize(0,38));paste->SetName("import-paste-lyrics");paste->SetMinSize(FromDIP(wxSize(0,38)));paste->Bind(wxEVT_BUTTON,[this](wxCommandEvent&){try{ImportLyrics();}catch(std::exception const& e){SetStatus(show(e.what()));}});prepare->Add(paste,1);body[0]->Add(prepare,0,wxEXPAND|wxLEFT|wxRIGHT|wxBOTTOM,14);
    provider=new wxChoice(page[0],wxID_ANY);provider->Append(L"ElevenLabs · Scribe v2");provider->Append(L"Microsoft MAI · Azure Speech");provider->SetSelection(0);provider->SetMinSize(wxSize(0,-1));auto services=new wxBoxSizer(wxHORIZONTAL);services->Add(provider,1,wxALIGN_CENTER_VERTICAL|wxRIGHT,6);auto settings=new StudioButton(page[0],L"API 设置",StudioButton::Kind::Secondary,wxSize(76,30));settings->Bind(wxEVT_BUTTON,[this](wxCommandEvent&){try{Configure();}catch(std::exception const& e){SetStatus(show(e.what()));}});services->Add(settings,0);task_actions.push_back(settings);body[0]->Add(services,0,wxEXPAND|wxLEFT|wxRIGHT|wxBOTTOM,14);
    auto modes=new wxBoxSizer(wxHORIZONTAL);auto online=new StudioButton(page[0],L"③ 联网转录与匹配",StudioButton::Kind::Primary,wxSize(0,38));online->SetName("import-online");online->SetMinSize(FromDIP(wxSize(0,38)));online->Bind(wxEVT_BUTTON,[this](wxCommandEvent&){Start("transcribe_match",false);});modes->Add(online,1,wxRIGHT,6);task_actions.push_back(online);auto offline=new StudioButton(page[0],L"③ 离线分词制作",StudioButton::Kind::Secondary,wxSize(0,38));offline->SetName("import-offline");offline->SetMinSize(FromDIP(wxSize(0,38)));offline->Bind(wxEVT_BUTTON,[this](wxCommandEvent&){try{LocalSegment("words",true);}catch(std::exception const& e){SetStatus(show(e.what()));}});modes->Add(offline,1);task_actions.push_back(offline);body[0]->Add(modes,0,wxEXPAND|wxLEFT|wxRIGHT|wxBOTTOM,14);
    auto import_page=page[0];auto more_panel=new wxPanel(import_page);more_panel->SetBackgroundColour(*wxWHITE);more_panel->Hide();auto import_more=new StudioButton(import_page,L"更多导入 · 已有转录／打开工程 ▾",StudioButton::Kind::Secondary,wxSize(0,32));import_more->SetName("import-more");import_more->SetMinSize(FromDIP(wxSize(0,32)));import_more->Bind(wxEVT_BUTTON,[more_panel,import_page,import_more](wxCommandEvent&){bool show=!more_panel->IsShown();more_panel->Show(show);import_more->SetLabel(show?L"收起更多导入 ▴":L"更多导入 · 已有转录／打开工程 ▾");import_page->Layout();if(auto scroll=dynamic_cast<wxScrolledWindow*>(import_page))scroll->FitInside();});body[0]->Add(import_more,0,wxEXPAND|wxLEFT|wxRIGHT|wxBOTTOM,14);body[0]->Add(more_panel,0,wxEXPAND);page[0]=more_panel;body[0]=new wxBoxSizer(wxVERTICAL);page[0]->SetSizer(body[0]);
    note(0,L"联网服务可能计费。已有转录可复用；离线分词不需要密钥，时间需自己校准。");
    button(0,L"复用已有转录（不再上传）",[this]{MatchExisting();},false,true);
    button(0,L"没有原歌词？仅生成识别初稿",[this]{Start("transcribe",false);},false,true);
    button(0,L"打开声稿工程 JSON",[this]{ImportProject();});
    button(0,L"导入 LRC 时间歌词（可选）",[this]{ImportLrc();});

    BuildCalibration(page[1],body[1]);
    note(1,L"转录辅助与自动分析",true);
    segment_scope=new wxChoice(page[1],wxID_ANY);segment_scope->Append(L"处理左侧选中的歌词");segment_scope->Append(L"处理全部未保护歌词");segment_scope->SetSelection(0);studio_ui::field(segment_scope);body[1]->Add(segment_scope,0,wxEXPAND|wxLEFT|wxRIGHT|wxBOTTOM,14);
    button(1,L"转录辅助二次校对 · 读音与短空隙",[this]{RefineDialog();},true,true);
    auto advanced=new wxCollapsiblePane(page[1],wxID_ANY,L"分词、自动对齐与批量工具",wxDefaultPosition,wxDefaultSize,wxCP_DEFAULT_STYLE|wxCP_NO_TLW_RESIZE);advanced->SetName("timing-advanced");body[1]->Add(advanced,0,wxEXPAND|wxLEFT|wxRIGHT|wxBOTTOM,10);
    auto scroll_page=page[1];advanced->Bind(wxEVT_COLLAPSIBLEPANE_CHANGED,[scroll_page](wxCollapsiblePaneEvent&){scroll_page->Layout();if(auto scroll=dynamic_cast<wxScrolledWindow*>(scroll_page))scroll->FitInside();});page[1]=advanced->GetPane();body[1]=new wxBoxSizer(wxVERTICAL);page[1]->SetSizer(body[1]);
    note(1,L"词典提供初稿，特殊唱法结合转录和 DeepSeek 复核。自动结果先审核。");
    button(1,L"本地按原歌词分词＋假名",[this]{LocalSegment("words");},true,true);
    button(1,L"按读音拆演唱音节（不联网）",[this]{LocalSegment("mora");},false,true);
    button(1,L"开始逐音节校准",[this]{if(context->karaoke)context->karaoke->SetEnabled(true);},true);
    button(1,L"对齐所选歌词 · ElevenLabs",[this]{Start("align");},false,true);
    local_range=new wxCheckBox(page[1],wxID_ANY,L"仅对齐选中时间段（已有粗轴）");body[1]->Add(local_range,0,wxLEFT|wxRIGHT|wxBOTTOM,14);
    loop=new wxCheckBox(page[1],wxID_ANY,L"循环试听当前选区／音节");loop->Bind(wxEVT_CHECKBOX,[this](wxCommandEvent&){if(!context->project->AudioProvider()){loop->SetValue(false);SetStatus(L"请先添加音视频，再循环试听。");return;}if(loop->GetValue()){context->audioController->PlayPrimaryRange();loop_timer.Start(120);}else{loop_timer.Stop();context->audioController->Stop();}});body[1]->Add(loop,0,wxLEFT|wxRIGHT|wxBOTTOM,14);
    button(1,L"批量偏移时间…",[this]{OffsetDialog();});
    note(1,L"整体偏移会同步移动假名音节与静音间隔；可以撤销。不会自动改变音节间距。");
    button(1,L"检查字幕并定位问题",[this]{ShowStage(3);RefreshChecks();});

    note(2,L"读音与译文",true);
    button(2,L"DeepSeek 结合转录复核注音与译文",[this]{RefineDialog(true);},true,true);
    reading_evidence=note(2,L"转录辅助复核会显示原读音、建议和依据；人工注音受保护。");
    auto readings=new wxFlexGridSizer(2,6,10);readings->AddGrowableCol(0,1);readings->AddGrowableCol(1,1);
    readings->Add(new wxStaticText(page[2],wxID_ANY,L"整句假名"));readings->Add(new wxStaticText(page[2],wxID_ANY,L"整句罗马音"));
    kana=new wxTextCtrl(page[2],wxID_ANY);romaji=new wxTextCtrl(page[2],wxID_ANY);
    for(auto field:{kana,romaji}){field->SetMinSize(wxSize(0,-1));field->Bind(wxEVT_TEXT,[this](wxCommandEvent&){if(!loading)MarkDirty();});readings->Add(field,1,wxEXPAND);}
    body[2]->Add(readings,0,wxEXPAND|wxLEFT|wxRIGHT|wxBOTTOM,14);
    units=new wxGrid(page[2],wxID_ANY,wxDefaultPosition,FromDIP(wxSize(-1,182)));units->SetMinSize(FromDIP(wxSize(0,182)));units->CreateGrid(0,6);units->SetRowLabelSize(26);units->SetColLabelSize(30);units->SetLabelBackgroundColour(canvas);units->SetGridLineColour(wxColour(229,235,243));
    wxString columns[]={L"原文",L"假名",L"罗马音",L"开始ms",L"结束ms",L"来源"};int widths[]={40,65,56,60,60,44};
    for(int i=0;i<6;++i){units->SetColLabelValue(i,columns[i]);units->SetColSize(i,FromDIP(widths[i]));}units->Bind(wxEVT_GRID_CELL_CHANGED,[this](wxGridEvent&){if(!loading)MarkDirty();});body[2]->Add(units,0,wxEXPAND|wxLEFT|wxRIGHT|wxBOTTOM,10);
    auto word_tools=new wxBoxSizer(wxHORIZONTAL);
    auto split_word=new StudioButton(page[2],L"拆分所选词…",StudioButton::Kind::Secondary,wxSize(0,32));split_word->Bind(wxEVT_BUTTON,[this](wxCommandEvent&){try{SplitWord();}catch(std::exception const& e){wxMessageBox(show(e.what()),L"拆分词组",wxOK|wxICON_INFORMATION,this);}});word_tools->Add(split_word,1,wxRIGHT,8);
    auto merge_word=new StudioButton(page[2],L"与下一词合并",StudioButton::Kind::Secondary,wxSize(0,32));merge_word->Bind(wxEVT_BUTTON,[this](wxCommandEvent&){try{MergeWord();}catch(std::exception const& e){wxMessageBox(show(e.what()),L"合并词组",wxOK|wxICON_INFORMATION,this);}});word_tools->Add(merge_word,1);body[2]->Insert(body[2]->GetItemCount()-1,word_tools,0,wxEXPAND|wxLEFT|wxRIGHT|wxBOTTOM,10);
    units->Bind(wxEVT_GRID_EDITOR_SHOWN,[this](wxGridEvent& event){if(!loading)MarkDirty();event.Skip();});
    auto translation_label=new wxStaticText(page[2],wxID_ANY,L"中文译文");body[2]->Add(translation_label,0,wxLEFT|wxRIGHT|wxBOTTOM,10);
    translation=new wxTextCtrl(page[2],wxID_ANY,"",wxDefaultPosition,wxSize(-1,58),wxTE_MULTILINE);translation->SetMinSize(wxSize(0,58));translation->Bind(wxEVT_TEXT,[this](wxCommandEvent&){if(!loading)MarkDirty();});body[2]->Add(translation,0,wxEXPAND|wxLEFT|wxRIGHT|wxBOTTOM,10);
    auto confirmations=new wxBoxSizer(wxHORIZONTAL);
    locked=new wxCheckBox(page[2],wxID_ANY,L"保护人工结果");locked->SetToolTip(L"阻止 AI 或历史任务覆盖本行");locked->Bind(wxEVT_CHECKBOX,[this](wxCommandEvent&){MarkDirty();});confirmations->Add(locked,0,wxRIGHT,16);
    reviewed=new wxCheckBox(page[2],wxID_ANY,L"时间已人工确认");reviewed->Bind(wxEVT_CHECKBOX,[this](wxCommandEvent&){MarkDirty();});confirmations->Add(reviewed,0);body[2]->Add(confirmations,0,wxLEFT|wxRIGHT|wxBOTTOM,10);
    note(2,L"用 | 拆演唱音节，例如 きょ|う。新增时间待校准；底部“应用本行修改”始终可用。");
    button(2,L"放弃未保存编辑并重新读取",[this]{DiscardFields();});

    note(3,L"检查、预览与交付",true);
    button(3,L"导出卡拉 OK / 注音 ASS",[this]{Export(true);},true,true);
    quality_summary=note(3,L"运行检查，查看待校准、读音缺失和时间问题。");
    issue_filter=new wxChoice(page[3],wxID_ANY);for(auto value:{L"所有问题",L"格式错误",L"时间待校准",L"缺少假名",L"尚未人工确认",L"匹配待确认"})issue_filter->Append(value);issue_filter->SetSelection(0);issue_filter->SetMinSize(wxSize(0,-1));issue_filter->Bind(wxEVT_CHOICE,[this](wxCommandEvent&){RefreshChecks();});body[3]->Add(issue_filter,0,wxEXPAND|wxLEFT|wxRIGHT|wxBOTTOM,14);
    issues=new wxListBox(page[3],wxID_ANY,wxDefaultPosition,FromDIP(wxSize(-1,140)),0,nullptr,wxLB_SINGLE|wxHSCROLL);issues->SetMinSize(wxSize(0,FromDIP(140)));issues->Bind(wxEVT_LISTBOX,[this](wxCommandEvent& e){if(e.GetSelection()>=0&&e.GetSelection()<int(issue_ids.size()))SelectLine(issue_ids[e.GetSelection()]);});body[3]->Add(issues,0,wxEXPAND|wxLEFT|wxRIGHT|wxBOTTOM,14);
    button(3,L"重新检查字幕",[this]{RefreshChecks();});
    auto visibility=new wxBoxSizer(wxHORIZONTAL);show_ruby=new wxCheckBox(page[3],wxID_ANY,L"假名");show_romaji=new wxCheckBox(page[3],wxID_ANY,L"罗马音");show_translation=new wxCheckBox(page[3],wxID_ANY,L"译文");for(auto checkbox:{show_ruby,show_romaji,show_translation}){checkbox->SetValue(true);visibility->Add(checkbox,0,wxRIGHT,14);checkbox->Bind(wxEVT_CHECKBOX,[this](wxCommandEvent&){preview_stale=true;UpdateOverview();});}body[3]->Add(visibility,0,wxLEFT|wxRIGHT|wxBOTTOM,14);
    preview_label=note(3,L"尚未刷新注音成品预览。");
    button(3,L"刷新视频中的注音成品预览",[this]{Preview();},false,true);

    button(3,L"导出 JSON / SRT / TXT",[this]{Export(false);},false,true);
    note(3,L"Ctrl+S 保存可编辑 ASS 工程。SRT / TXT 不包含逐音节高亮。 ");

    root->Add(pages,1,wxEXPAND|wxLEFT|wxRIGHT,10);
    root->Add(studio_ui::rule(this),0,wxEXPAND|wxLEFT|wxRIGHT|wxTOP,14);
    task_progress=new wxGauge(this,wxID_ANY,100,wxDefaultPosition,FromDIP(wxSize(-1,4)));root->Add(task_progress,0,wxEXPAND|wxLEFT|wxRIGHT|wxTOP,14);
    status=new wxStaticText(this,wxID_ANY,L"第一次使用可点“新手指南”；自动结果先审核，再应用。",wxDefaultPosition,FromDIP(wxSize(-1,48)));status->SetMinSize(wxSize(0,FromDIP(48)));root->Add(status,0,wxEXPAND|wxLEFT|wxRIGHT|wxTOP,14);
    auto footer=new wxBoxSizer(wxHORIZONTAL);
    cancel_button=new StudioButton(this,L"取消任务",StudioButton::Kind::Secondary,wxSize(0,34));cancel_button->Bind(wxEVT_BUTTON,[this](wxCommandEvent&){Cancel();});footer->Add(cancel_button,1,wxRIGHT,8);
    review_button=new StudioButton(this,L"审核结果",StudioButton::Kind::Secondary,wxSize(0,34));review_button->Bind(wxEVT_BUTTON,[this](wxCommandEvent&){ReviewPending();});footer->Add(review_button,1,wxRIGHT,8);
    auto history=new StudioButton(this,L"任务记录",StudioButton::Kind::Secondary,wxSize(0,34));history->Bind(wxEVT_BUTTON,[this](wxCommandEvent&){TaskHistory();});footer->Add(history,1);
    root->Add(footer,0,wxEXPAND|wxLEFT|wxRIGHT|wxBOTTOM,16);
    save_button=new StudioButton(this,L"应用本行修改",StudioButton::Kind::Primary,wxSize(0,42));save_button->SetName(L"save-current-changes");save_button->Bind(wxEVT_BUTTON,[this](wxCommandEvent&){FlushChanges();});root->Add(save_button,0,wxEXPAND|wxLEFT|wxRIGHT|wxBOTTOM,16);
    save_button->SetToolTip(L"同步当前行改动到工程；Ctrl+S 保存工程文件。");
    for(auto control:std::vector<wxWindow*>{provider,local_range,loop,kana,romaji,translation,locked,reviewed,issue_filter,issues,show_ruby,show_romaji,show_translation})studio_ui::field(control);
    units->SetDefaultCellFont(studio_ui::font(9));units->SetLabelFont(studio_ui::font(9,true));units->SetLabelBackgroundColour(studio_ui::soft);units->SetLabelTextColour(ink);units->SetGridLineColour(studio_ui::line);units->SetSelectionBackground(studio_ui::tint);units->SetSelectionForeground(ink);units->SetDefaultCellTextColour(ink);units->SetDefaultCellBackgroundColour(studio_ui::paper);units->SetBackgroundColour(studio_ui::paper);units->GetGridWindow()->SetBackgroundColour(studio_ui::paper);units->SetDefaultCellAlignment(wxALIGN_LEFT,wxALIGN_CENTER);
    SetSizer(root);ShowStage(0);UpdateBusy();
}

void StudioPanel::ShowStage(int stage) {
    if(stage<0||stage>=4)return;pages->SetSelection(stage);
    current_label->Show(stage!=0);dirty_label->Show(stage!=0);GetSizer()->Show(line_navigation,stage!=0);
    if(stage==1&&context->karaoke&&context->project->AudioProvider()){if(!context->frame->IsAudioShown())context->frame->SetDisplayMode(-1,1);if(!context->karaoke->IsEnabled())context->karaoke->SetEnabled(true);}
    for(int i=0;i<4;++i){stages[i]->SetValue(i==stage);}
    if(stage==3)RefreshChecks();Layout();
}
void StudioPanel::MarkDirty() {fields_dirty=true;UpdateOverview();}
void StudioPanel::SetStatus(wxString const& message) {
    auto value=wrapped(status,message,FromDIP(350));int breaks=0;size_t last=0;
    for(size_t i=0;i<value.size();++i)if(value[i]=='\n'){++breaks;if(breaks==2){last=i;break;}}
    if(last)value=value.Left(last)+L"…";
    status->SetToolTip(message);
    if(status->GetLabel()!=value){status->SetLabel(value);Layout();}
}
void StudioPanel::UpdateOverview() {
    if(!overview)return;
    auto media=context->project->VideoName();if(media.empty())media=context->project->AudioName();
    auto name=media.empty()?wxString(L"未添加媒体"):wxString(media.filename().wstring());
    auto full_name=name;if(name.size()>28)name=name.Left(28)+L"…";
    auto rows=ReadLines(false);int confirmed=0;for(auto const& row:rows)confirmed+=flag(static_cast<json::Object const&>(row),"reviewed");auto summary=rows.empty()?(media.empty()?wxString(L"先添加媒体，再粘贴每行一句的歌词"):wxString(L"已添加媒体，接下来粘贴歌词")):wxString::Format(L"已确认 %d / %zu 句  ·  %s",confirmed,rows.size(),name);overview->SetLabel(wrapped(overview,summary,FromDIP(350)));overview->SetMinSize(wxSize(0,-1));overview->SetToolTip(full_name);
    auto line=std::find_if(context->ass->Events.begin(),context->ass->Events.end(),[this](auto const& value){return value.Id==active_id;});
    if(line!=context->ass->Events.end()){auto data=ReadLine(&*line);auto text=show(field(static_cast<json::Object const&>(data),"text"));text.Replace(L"\n",L" / ");if(text.size()>20)text=text.Left(20)+L"…";current_label->SetLabel(text.empty()?wxString(L"尚未添加歌词"):wxString::Format(L"第 %d 行 · %s",line->Row+1,text));}
    else current_label->SetLabel(L"当前未选择歌词");
    dirty_label->SetLabel(fields_dirty||timing_dirty?L"● 本行有草稿 · 应用修改或 Ctrl+S":L"✓ 本行已应用 · Ctrl+S 保存文件");dirty_label->SetForegroundColour(fields_dirty||timing_dirty?wxColour(173,104,15):muted);
    if(save_button)save_button->Enable((fields_dirty||timing_dirty)&&active_id>=0);
    if(preview_label){preview_label->SetLabel(preview_stale?L"● 内容或显示选项已改变，请刷新成品预览。":preview_active?L"✓ 已显示当前注音成品预览。":L"尚未刷新注音成品预览。");preview_label->SetForegroundColour(preview_stale?wxColour(173,104,15):preview_active?wxColour(23,125,93):muted);}
    Layout();if(context->studioShell)context->studioShell->UpdateState();
}
void StudioPanel::UpdateBusy() {
    if(!cancel_button)return;cancel_button->Enable(pid!=0);review_button->Enable(has_pending_result&&pid==0);for(auto control:task_actions)control->Enable(pid==0);
    if(pid)task_progress->Pulse();else task_progress->SetValue(0);if(context->studioShell)context->studioShell->UpdateState();
}
void StudioPanel::SelectLine(int id) {
    if(!FlushChanges())return;
    for(auto& line:context->ass->Events)if(line.Id==id){context->selectionController->SetSelectionAndActive({&line},&line);context->subsGrid->ScrollTo(line.Row);if(context->project->AudioProvider())context->audioBox->ScrollToActiveLine();if(context->project->VideoProvider())context->videoController->JumpToTime(line.Start);return;}
}
void StudioPanel::Navigate(int direction,bool unreviewed) {
    if(!FlushChanges())return;std::vector<int> ids;
    for(auto& line:context->ass->Events)if(!line.Comment&&!line.GetStrippedText().empty()){
        if(!unreviewed){ids.push_back(line.Id);continue;}
        auto data=ReadLine(&line);auto const& object=static_cast<json::Object const&>(data);
        if(!flag(object,"reviewed"))ids.push_back(line.Id);
    }
    if(ids.empty()){SetStatus(unreviewed?L"全部歌词已人工确认。":L"请先导入歌词。");return;}
    auto current=context->selectionController->GetActiveLine();
    int current_row=current?current->Row:-1;AssDialogue *target=nullptr;
    if(direction>=0){for(auto& line:context->ass->Events)if(line.Row>current_row&&std::find(ids.begin(),ids.end(),line.Id)!=ids.end()){target=&line;break;}}
    else for(auto& line:context->ass->Events)if(line.Row<current_row&&std::find(ids.begin(),ids.end(),line.Id)!=ids.end())target=&line;
    if(!target&&unreviewed){SelectLine(ids.front());return;}
    if(target)SelectLine(target->Id);else SetStatus(direction>0?L"已经是最后一行。":L"已经是第一行。");
}
void StudioPanel::RefreshChecks() {
    if(!issues)return;auto lines=ReadLines(false);auto report=studio_workflow::inspect(lines);issues->Clear();issue_ids.clear();
    std::set<std::string> affected;size_t errors=0;for(auto const& item:report){affected.insert(item.id);errors+=item.error;}
    quality_summary->SetLabel(wxString::Format(L"%zu 行歌词 · %zu 行待检查 · %zu 个格式错误",lines.size(),affected.size(),errors));quality_summary->Wrap(380);
    int filter=issue_filter->GetSelection();
    for(auto const& issue:report){if((filter==1&&!issue.error)||(filter==2&&issue.code!="timing"&&issue.code!="overlap")||(filter==3&&issue.code!="reading")||(filter==4&&issue.code!="review")||(filter==5&&issue.code!="match"))continue;
        int id=std::stoi(issue.id);int row=0;for(auto& line:context->ass->Events)if(line.Id==id){row=line.Row+1;break;}
        issues->Append(wxString::Format(L"%s  第 %d 行 · %s",issue.error?L"错误":L"提示",row,show(issue.message)));issue_ids.push_back(id);
    }
    if(lines.empty())issues->Append(L"尚无歌词，请先在导入阶段添加歌词。");
    else if(report.empty())issues->Append(L"✓ 检查通过，仍建议完整试听。 ");
}
void StudioPanel::OffsetDialog() {
    if(!FlushChanges())return;wxDialog dialog(this,wxID_ANY,L"批量偏移时间",wxDefaultPosition,FromDIP(wxSize(430,280)));auto layout=new wxBoxSizer(wxVERTICAL);
    layout->Add(new wxStaticText(&dialog,wxID_ANY,L"正数延后，负数提前。单位为毫秒。\n原有音节间距、假名和锁定状态会保留。"),0,wxALL,18);
    auto delta=new wxSpinCtrl(&dialog,wxID_ANY,"",wxDefaultPosition,wxDefaultSize,wxSP_ARROW_KEYS,-3600000,3600000,0);delta->SetIncrement(10);layout->Add(delta,0,wxEXPAND|wxLEFT|wxRIGHT|wxBOTTOM,18);
    auto scope=new wxChoice(&dialog,wxID_ANY);scope->Append(L"仅所选歌词行");scope->Append(L"全部歌词行");scope->SetSelection(0);layout->Add(scope,0,wxEXPAND|wxLEFT|wxRIGHT|wxBOTTOM,18);layout->Add(dialog.CreateButtonSizer(wxOK|wxCANCEL),0,wxEXPAND|wxALL,18);dialog.SetSizer(layout);
    if(dialog.ShowModal()==wxID_OK)ApplyOffset(delta->GetValue(),scope->GetSelection()==0);
}
void StudioPanel::ApplyOffset(int delta,bool selected) {
    if(delta%10)throw std::runtime_error("ASS 的时间精度为 10 ms，请输入 10 的整数倍");
    if(!FlushChanges()||delta==0)return;auto values=ReadLines(selected);std::vector<std::pair<AssDialogue*,json::UnknownElement>> pending;
    for(auto const& value:values){auto const& object=static_cast<json::Object const&>(value);int id=std::stoi(field(object,"id"));for(auto& line:context->ass->Events)if(line.Id==id){pending.emplace_back(&line,studio_workflow::shifted(value,delta));break;}}
    if(pending.empty())throw std::runtime_error("请选择需要偏移的歌词行");
    // Validate all lines first, then preserve original ASS tags by moving only
    // the line origin. Relative karaoke durations do not change.
    for(auto& entry:pending){auto const& object=static_cast<json::Object const&>(entry.second);entry.first->Start=studio_document::time(object,"start");entry.first->End=studio_document::time(object,"end");WriteLine(entry.first,entry.second,false);}
    context->ass->Commit(L"批量偏移歌词时间",AssFile::COMMIT_DIAG_FULL|AssFile::COMMIT_EXTRADATA);RefreshLine();SetStatus(wxString::Format(L"已将 %zu 行偏移 %+d ms；可撤销，时间需重新确认。",pending.size(),delta));
}
void StudioPanel::OpenMedia() {
    wxFileDialog dialog(this,L"添加音视频或字幕","","",L"音视频、字幕和工程|*.mp4;*.mkv;*.mov;*.webm;*.avi;*.mp3;*.wav;*.flac;*.m4a;*.ogg;*.aac;*.ass;*.srt;*.json;*.lrc|所有文件|*.*",wxFD_OPEN|wxFD_FILE_MUST_EXIST);
    if(dialog.ShowModal()!=wxID_OK)return;auto path=std::filesystem::path(dialog.GetPath().ToStdWstring());if(!OpenStudioFile(path))context->project->LoadList({agi::fs::path(path)});
}
void StudioPanel::ImportLrc() {wxFileDialog dialog(this,L"导入 LRC 歌词","","",L"标准 LRC (*.lrc)|*.lrc",wxFD_OPEN|wxFD_FILE_MUST_EXIST);if(dialog.ShowModal()==wxID_OK)ImportLrcFile(std::filesystem::path(dialog.GetPath().ToStdWstring()));}
void StudioPanel::ImportLrcFile(std::filesystem::path const& path) {
    auto encoding=CharSetDetect::GetEncoding(agi::fs::path(path));
    TextFileReader reader(agi::fs::path(path),encoding.c_str(),false);std::string contents;while(reader.HasMoreLines())contents+=reader.ReadLineFromFile()+"\n";
    int duration=0;if(auto audio=context->project->AudioProvider())duration=int(audio->GetNumSamples()*1000/audio->GetSampleRate());auto values=studio_workflow::lrc(contents,duration);
    if(!FlushChanges())return;AssDialogue *first=nullptr;
    bool placeholder=context->ass->Events.size()==1&&context->ass->Events.begin()->GetStrippedText().empty();
    for(auto const& value:values){auto line=placeholder?&*context->ass->Events.begin():new AssDialogue;WriteLine(line,value,true);if(!placeholder)context->ass->Events.push_back(*line);placeholder=false;if(!first)first=line;}
    context->ass->Commit(L"导入 LRC 时间歌词",AssFile::COMMIT_DIAG_ADDREM|AssFile::COMMIT_EXTRADATA);context->selectionController->SetSelectionAndActive({first},first);ShowStage(1);SetStatus(wxString::Format(L"已导入 %zu 行 LRC；句间结束点为粗轴，请继续校准。",values.size()));
}
bool StudioPanel::OpenStudioFile(std::filesystem::path const& path) {
    auto extension=path.extension().wstring();std::transform(extension.begin(),extension.end(),extension.begin(),::towlower);
    if(extension==L".json"){if(OpenProject(path))ShowStage(1);return true;}
    if(extension==L".lrc"){ImportLrcFile(path);return true;}return false;
}

void StudioPanel::LocalSegment(std::string const& mode,bool incomplete_only) {
    if(pid)throw std::runtime_error("请先等待当前任务完成");if(!FlushChanges())return;
    auto lines=ReadLines(!incomplete_only&&(!segment_scope||segment_scope->GetSelection()==0));
    if(incomplete_only)lines.erase(std::remove_if(lines.begin(),lines.end(),[&](auto const& value){auto const& row=static_cast<json::Object const&>(value);auto const& parts=static_cast<json::Array const&>(row.at("units"));return studio_pauses::locked(value)||flag(row,"reviewed")||(mode=="words"?!parts.empty():!std::any_of(parts.begin(),parts.end(),studio_workflow::needs_mora));}),lines.end());
    if(lines.empty())throw std::runtime_error("当前范围没有需要处理的歌词；可在校轴页展开分词工具手动选择范围");
    snapshots.clear();for(auto const& value:lines){auto const& object=static_cast<json::Object const&>(value);snapshots[std::stoi(field(object,"id"))]=studio_workflow::encode(value);}
    json::Object request;request["action"]="segment";request["mode"]=mode;request["provider"]="local";request["lines"]=std::move(lines);Launch(std::move(request));
}

void StudioPanel::CommitWordEdit(json::UnknownElement const& value) {
    auto line=context->selectionController->GetActiveLine();if(!line)throw std::runtime_error("请先选择歌词");
    studio_document::karaoke(value);WriteLine(line,value,true);fields_dirty=false;
    context->ass->Commit(L"手动调整分词",AssFile::COMMIT_DIAG_FULL|AssFile::COMMIT_EXTRADATA);RefreshLine();SetStatus(L"已调整词组，可撤销。新增边界为估算值，请在时间轴试听校准。");
}

void StudioPanel::SplitWord() {
    int row=units->GetGridCursorRow();if(!FlushChanges())return;auto line=context->selectionController->GetActiveLine();if(!line)return;
    auto value=ReadLine(line);auto const& list=static_cast<json::Array const&>(static_cast<json::Object const&>(value).at("units"));
    if(row<0||row>=int(list.size()))throw std::runtime_error("先在表格中点选一个词组；没有词组时可先本地分词");
    wxDialog dialog(this,wxID_ANY,L"拆分词组 · 保持原歌词",wxDefaultPosition,FromDIP(wxSize(580,300)));auto layout=new wxBoxSizer(wxVERTICAL);
    auto note=new wxStaticText(&dialog,wxID_ANY,L"用 | 标出词组边界，例如 抱き|しめ。必须保持原文和空格不变。假名可留空，之后再补；新时间按原词范围估算。");note->Wrap(520);layout->Add(note,0,wxALL,16);
    auto text=new wxTextCtrl(&dialog,wxID_ANY,show(field(static_cast<json::Object const&>(list[row]),"text")));layout->Add(text,0,wxEXPAND|wxLEFT|wxRIGHT|wxBOTTOM,16);
    layout->Add(new wxStaticText(&dialog,wxID_ANY,L"对应假名（可选，同样用 | 分组）"),0,wxLEFT|wxBOTTOM,16);auto reading=new wxTextCtrl(&dialog,wxID_ANY);layout->Add(reading,0,wxEXPAND|wxLEFT|wxRIGHT|wxBOTTOM,16);layout->Add(dialog.CreateButtonSizer(wxOK|wxCANCEL),0,wxEXPAND|wxALL,16);dialog.SetSizer(layout);
    while(dialog.ShowModal()==wxID_OK){try{
        std::vector<std::string> parts,readings;for(auto const& part:wxSplit(text->GetValue(),'|'))parts.emplace_back(part.utf8_str());
        if(!reading->GetValue().empty())for(auto const& part:wxSplit(reading->GetValue(),'|'))readings.emplace_back(part.utf8_str());
        CommitWordEdit(studio_editing::split(value,row,parts,readings));return;
    }catch(std::exception const& error){wxMessageBox(show(error.what()),L"无法拆分",wxOK|wxICON_INFORMATION,&dialog);}}
}

void StudioPanel::MergeWord() {
    int row=units->GetGridCursorRow();if(!FlushChanges())return;auto line=context->selectionController->GetActiveLine();if(!line)return;
    CommitWordEdit(studio_editing::merge(ReadLine(line),row));
}

void StudioPanel::MatchExisting() {
    if(pid)throw std::runtime_error("请先等待当前任务完成");
    if(!FlushChanges())return;
    auto home=std::filesystem::path(wxStandardPaths::Get().GetUserDataDir().ToStdWstring())/"tasks";
    std::vector<std::filesystem::path> files;
    if(std::filesystem::is_directory(home))for(auto const& entry:std::filesystem::directory_iterator(home))if(entry.is_directory()&&std::filesystem::is_regular_file(entry.path()/"result.json"))files.push_back(entry.path());
    std::sort(files.begin(),files.end(),std::greater<std::filesystem::path>());
    wxDialog dialog(this,wxID_ANY,L"本地重匹配 · 原歌词为准",wxDefaultPosition,FromDIP(wxSize(700,610)));
    auto layout=new wxBoxSizer(wxVERTICAL);auto note=new wxStaticText(&dialog,wxID_ANY,L"复用已有识别时间，不上传或调用 API。原歌词的空格、标点和分行保持不变。\n修正错位时，选中对应歌词，并指定该句实际出现的时间段（秒）。");note->Wrap(630);layout->Add(note,0,wxALL,18);
    auto list=new wxListBox(&dialog,wxID_ANY);std::vector<std::filesystem::path> sources;
    for(auto const& folder:files){if(sources.size()>=50)break;try{
        std::ifstream task_stream(folder/"task.json"),result_stream(folder/"result.json");auto task=agi::json_util::parse(task_stream),result=agi::json_util::parse(result_stream);
        auto const& meta=static_cast<json::Object const&>(task);auto const& data=static_cast<json::Object const&>(result);auto kind=field(meta,"action");
        if((!flag(data,"ok")&&data.find("transcript")==data.end())||(kind!="transcribe"&&data.find("transcript")==data.end()))continue;
        auto media=std::filesystem::path(show(field(meta,"media")).ToStdWstring()).filename();
        list->Append(show(field(meta,"created_at"))+L"  "+wxString(media.wstring()));sources.push_back(folder/"result.json");
    }catch(...) {}}
    layout->Add(list,1,wxEXPAND|wxLEFT|wxRIGHT,18);if(!sources.empty())list->SetSelection(0);
    auto selected=new wxCheckBox(&dialog,wxID_ANY,L"仅匹配左侧选中的歌词行（修正局部时推荐）");selected->SetValue(true);layout->Add(selected,0,wxALL,12);
    auto scoped=new wxCheckBox(&dialog,wxID_ANY,L"在指定时间段内寻找，避免选到其他副歌");layout->Add(scoped,0,wxLEFT|wxRIGHT|wxBOTTOM,12);
    auto times=new wxBoxSizer(wxHORIZONTAL);auto active=context->selectionController->GetActiveLine();double begin_value=active?int(active->Start)/1000.0:0,end_value=active?int(active->End)/1000.0:5;
    auto begin=new wxSpinCtrlDouble(&dialog,wxID_ANY,"",wxDefaultPosition,FromDIP(wxSize(120,-1)),wxSP_ARROW_KEYS,0,2147480,begin_value,.1),end=new wxSpinCtrlDouble(&dialog,wxID_ANY,"",wxDefaultPosition,FromDIP(wxSize(120,-1)),wxSP_ARROW_KEYS,0,2147480,end_value,.1);begin->SetDigits(2);end->SetDigits(2);begin->Enable(false);end->Enable(false);
    times->Add(new wxStaticText(&dialog,wxID_ANY,L"开始秒"),0,wxALIGN_CENTER_VERTICAL|wxRIGHT,8);times->Add(begin,1,wxRIGHT,12);times->Add(new wxStaticText(&dialog,wxID_ANY,L"结束秒"),0,wxALIGN_CENTER_VERTICAL|wxRIGHT,8);times->Add(end,1,wxRIGHT,12);auto listen=new wxButton(&dialog,wxID_ANY,L"试听范围");times->Add(listen,0);layout->Add(times,0,wxEXPAND|wxLEFT|wxRIGHT|wxBOTTOM,12);
    scoped->Bind(wxEVT_CHECKBOX,[&](wxCommandEvent&){begin->Enable(scoped->GetValue());end->Enable(scoped->GetValue());});
    bool range_played=false;listen->Bind(wxEVT_BUTTON,[&](wxCommandEvent&){if(context->project->AudioProvider()&&end->GetValue()>begin->GetValue()){context->audioController->PlayRange(TimeRange(int(begin->GetValue()*1000),int(end->GetValue()*1000)));range_played=true;}});
    auto stop=new wxButton(&dialog,wxID_ANY,L"停止");times->Add(stop,0,wxLEFT,6);stop->Bind(wxEVT_BUTTON,[&](wxCommandEvent&){context->audioController->Stop();});
    auto buttons=new wxBoxSizer(wxHORIZONTAL);auto browse=new wxButton(&dialog,wxID_ANY,L"浏览转录 JSON…");buttons->Add(browse,1,wxRIGHT,12);buttons->Add(new wxButton(&dialog,wxID_OK,L"使用所选转录"),1,wxRIGHT,12);buttons->Add(new wxButton(&dialog,wxID_CANCEL,L"取消"));layout->Add(buttons,0,wxEXPAND|wxALL,18);
    std::filesystem::path file;
    browse->Bind(wxEVT_BUTTON,[&](wxCommandEvent&){wxFileDialog open(&dialog,L"打开转录结果 JSON","","",L"JSON (*.json)|*.json",wxFD_OPEN|wxFD_FILE_MUST_EXIST);if(open.ShowModal()==wxID_OK){file=std::filesystem::path(open.GetPath().ToStdWstring());dialog.EndModal(wxID_OK);}});
    dialog.SetSizer(layout);auto answer=dialog.ShowModal();if(range_played)context->audioController->Stop();if(answer!=wxID_OK)return;
    if(file.empty()){if(list->GetSelection()<0)throw std::runtime_error("尚无已有转录，请先转录或浏览转录 JSON");file=sources.at(list->GetSelection());}
    std::ifstream input(file,std::ios::binary);auto result=agi::json_util::parse(input);auto const& object=static_cast<json::Object const&>(result);
    auto found=object.find("transcript");if(found==object.end())found=object.find("suggestions");if(found==object.end())found=object.find("lines");
    if(found==object.end())throw std::runtime_error("JSON 中没有可用转录行");auto const& transcript=static_cast<json::Array const&>(found->second);for(auto const& value:transcript)studio_document::karaoke(value);
    auto lines=ReadLines(selected->GetValue());if(lines.empty())throw std::runtime_error("请先粘贴原歌词");
    json::Object request;request["action"]="match";request["provider"]="local";request["transcript"]=studio_workflow::copy(found->second);
    auto media=context->project->VideoName();if(media.empty())media=context->project->AudioName();request["media"]=std::string(wxString(media.wstring()).utf8_str());
    if(scoped->GetValue()){int left=int(std::llround(begin->GetValue()*100))*10,right=int(std::llround(end->GetValue()*100))*10;if(right<=left)throw std::runtime_error("范围结束时间须晚于开始时间");json::Array range;range.emplace_back(left);range.emplace_back(right);request["match_range"]=std::move(range);}
    snapshots.clear();for(auto const& value:lines){auto const& line=static_cast<json::Object const&>(value);snapshots[std::stoi(field(line,"id"))]=studio_workflow::encode(value);}
    request["lines"]=std::move(lines);Launch(std::move(request));
}

void StudioPanel::EditCurrent() {
    if(!FlushChanges())return;auto line=context->selectionController->GetActiveLine();if(!line)return;
    auto data=ReadLine(line);auto const& object=static_cast<json::Object const&>(data);
    wxDialog dialog(this,wxID_ANY,L"编辑当前歌词",wxDefaultPosition,FromDIP(wxSize(620,420)));auto layout=new wxBoxSizer(wxVERTICAL);
    auto note=new wxStaticText(&dialog,wxID_ANY,L"修改原文会清除本行旧注音与逐字时间。只改时间会同比例移动音节；请再试听。起止单位：毫秒。");note->Wrap(550);layout->Add(note,0,wxALL,18);
    auto text=new wxTextCtrl(&dialog,wxID_ANY,show(field(object,"text")),wxDefaultPosition,wxDefaultSize,wxTE_MULTILINE);layout->Add(text,1,wxEXPAND|wxLEFT|wxRIGHT,18);
    auto times=new wxBoxSizer(wxHORIZONTAL);auto begin=new wxSpinCtrl(&dialog,wxID_ANY,"",wxDefaultPosition,wxDefaultSize,wxSP_ARROW_KEYS,0,2147480000,int(line->Start));auto end=new wxSpinCtrl(&dialog,wxID_ANY,"",wxDefaultPosition,wxDefaultSize,wxSP_ARROW_KEYS,0,2147480000,int(line->End));begin->SetIncrement(10);end->SetIncrement(10);times->Add(new wxStaticText(&dialog,wxID_ANY,L"开始"),0,wxALIGN_CENTER_VERTICAL|wxRIGHT,8);times->Add(begin,1,wxRIGHT,16);times->Add(new wxStaticText(&dialog,wxID_ANY,L"结束"),0,wxALIGN_CENTER_VERTICAL|wxRIGHT,8);times->Add(end,1);layout->Add(times,0,wxEXPAND|wxALL,18);
    auto confirmed=new wxCheckBox(&dialog,wxID_ANY,L"时间已人工确认");confirmed->SetValue(flag(object,"reviewed"));auto protect=new wxCheckBox(&dialog,wxID_ANY,L"保护本行人工结果");protect->SetValue(flag(object,"locked"));layout->Add(confirmed,0,wxLEFT|wxBOTTOM,18);layout->Add(protect,0,wxLEFT|wxBOTTOM,18);layout->Add(dialog.CreateButtonSizer(wxOK|wxCANCEL),0,wxEXPAND|wxALL,18);dialog.SetSizer(layout);
    while(dialog.ShowModal()==wxID_OK){try{UpdateCurrent(text->GetValue(),begin->GetValue(),end->GetValue(),confirmed->GetValue(),protect->GetValue());return;}catch(std::exception const& error){wxMessageBox(show(error.what()),L"无法保存当前行",wxOK|wxICON_INFORMATION,&dialog);}}
}

void StudioPanel::UpdateCurrent(wxString const& text,int start,int end,bool confirmed,bool protect) {
    if(!FlushChanges())return;auto line=context->selectionController->GetActiveLine();if(!line)throw std::runtime_error("请先选择歌词");
    if(text.empty()||start<0||end<=start||start%10||end%10)throw std::runtime_error("请输入歌词和有效起止时间（10 ms 的整数倍）");
    auto data=ReadLine(line);auto& value=static_cast<json::Object&>(data);auto original=field(value,"text");
    bool changed=show(original)!=text;int before_start=int(line->Start),duration=int(line->End)-before_start;
    if(changed){value["text"]=std::string(text.utf8_str());value["units"]=json::Array();for(auto key:{"kana","romaji","translation"})value[key]="";}
    else if(start!=int(line->Start)||end!=int(line->End)){
        auto scale=[&](json::Object& object){for(auto key:{"start","end"})object[key]=int(start+std::llround(double(studio_document::time(object,key)-before_start)*(end-start)/duration/10)*10);};
        for(auto& item:static_cast<json::Array&>(value.at("units"))){auto& unit=static_cast<json::Object&>(item);scale(unit);unit["source"]="estimated";auto parts=unit.find("highlights");if(parts!=unit.end())for(auto& part:static_cast<json::Array&>(parts->second)){auto& object=static_cast<json::Object&>(part);scale(object);object["source"]="estimated";}}
    }
    value["start"]=start;value["end"]=end;value["locked"]=protect;value["reviewed"]=confirmed;
    auto match=value.find("match");if(match!=value.end()&&(changed||start!=before_start||end!=int(line->End)))static_cast<json::Object&>(match->second)["status"]="manual";
    studio_document::karaoke(data);WriteLine(line,data,true);context->ass->Commit(L"编辑歌词与时间",AssFile::COMMIT_DIAG_FULL|AssFile::COMMIT_EXTRADATA);RefreshLine();
}
