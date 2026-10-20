// Copyright (c) 2026 Shengao Karaoke Studio contributors. MIT.
#include "studio_shell.h"
#include "studio_panel.h"
#include "studio_document.h"
#include "ass_dialogue.h"
#include "ass_file.h"
#include "audio_controller.h"
#include "audio_box.h"
#include "audio_karaoke.h"
#include "command/command.h"
#include "frame_main.h"
#include "include/aegisub/context.h"
#include "include/aegisub/menu.h"
#include "project.h"
#include "options.h"
#include "selection_controller.h"
#include "subs_controller.h"
#include "video_controller.h"
#include "video_display.h"
#include "async_video_provider.h"
#include <wx/button.h>
#include <wx/choice.h>
#include <wx/dc.h>
#include <wx/menu.h>
#include <wx/msgdlg.h>
#include <wx/sizer.h>
#include <wx/stattext.h>
#include <wx/textctrl.h>
#include <wx/slider.h>
#include <algorithm>
#include <functional>
#include <cmath>
#ifdef _WIN32
#include <windows.h>
#endif

namespace {
wxColour const ink=studio_ui::ink,muted=studio_ui::muted,accent=studio_ui::accent,canvas=studio_ui::canvas,line_color=studio_ui::line;
wxString show(std::string const& value){return wxString::FromUTF8(value);}
bool flag(json::Object const& object,char const *key){auto it=object.find(key);return it!=object.end()&&static_cast<json::Boolean const&>(it->second);}
wxString clipped(wxDC& dc,wxString text,int width){text.Replace(L"\n",L" / ");if(dc.GetTextExtent(text).x<=width)return text;while(!text.empty()&&dc.GetTextExtent(text+L"…").x>width)text.RemoveLast();return text+L"…";}
StudioButton *button(wxWindow *parent,wxString const& label,std::function<void()> run,bool primary=false,int width=-1){
    bool dark=parent->GetBackgroundColour()==studio_ui::header;
    auto style=dark?(primary?StudioButton::Kind::DarkPrimary:StudioButton::Kind::Dark):(primary?StudioButton::Kind::Primary:StudioButton::Kind::Secondary);
    auto value=new StudioButton(parent,label,style,wxSize(width,36));
    value->Bind(wxEVT_BUTTON,[parent,run](wxCommandEvent&){try{run();}catch(std::exception const& error){wxMessageBox(show(error.what()),L"声稿",wxOK|wxICON_INFORMATION,parent);}});return value;
}
}

StudioLyrics::StudioLyrics(wxWindow *parent,agi::Context *c):wxVListBox(parent,wxID_ANY,wxDefaultPosition,wxDefaultSize,wxLB_MULTIPLE|wxBORDER_NONE),context(c){
    SetBackgroundColour(studio_ui::paper);SetFont(studio_ui::font());SetSelectionBackground(studio_ui::paper);SetMinSize(FromDIP(wxSize(230,100)));SetName(L"歌词卡片列表");
    empty_hint=studio_ui::label(this,L"还没有歌词\n点击下方粘贴，每行一句\n已有 ASS / JSON 也可直接拖入",9,muted);empty_hint->SetName("lyrics-empty-state");empty_hint->Move(FromDIP(wxPoint(14,24)));
    Bind(wxEVT_LISTBOX,[this](wxCommandEvent& event){if(!syncing)ApplySelection(event.GetInt());});
    Bind(wxEVT_LISTBOX_DCLICK,[this](wxCommandEvent&){if(context->studioPanel)context->studioPanel->EditCurrent();});
    Bind(wxEVT_CONTEXT_MENU,[this](wxContextMenuEvent&){auto menu=menu::GetMenu("grid_context",wxID_HIGHEST+31000,context);menu::OpenPopupMenu(menu.get(),this);});
    BindConnection(c->ass->AddCommitListener([this](int,AssDialogue const*){Rebuild();}));
    BindConnection(c->selectionController->AddActiveLineListener([this](AssDialogue*){SyncSelection();}));
    BindConnection(c->selectionController->AddSelectionListener([this]{SyncSelection();}));
    Rebuild();
}
void StudioLyrics::SetFilter(wxString const& value,int kind){query=value.Lower();filter=kind;Rebuild();}
void StudioLyrics::Rebuild(){
    syncing=true;cards.clear();
    for(auto& line:context->ass->Events){if(line.Comment||line.GetStrippedText().empty())continue;
        auto data=context->studioPanel->DescribeLine(&line);auto const& value=static_cast<json::Object const&>(data);auto text=show(studio_document::text(value,"text")),reading=show(studio_document::text(value,"kana"));
        bool locked=flag(value,"locked"),reviewed=flag(value,"reviewed"),uncertain=false;wxString badge=reviewed?L"已确认":L"待校准";
        auto match=value.find("match");if(match!=value.end()){auto const& info=static_cast<json::Object const&>(match->second);auto state=studio_document::text(info,"status");uncertain=state=="uncertain"||state=="unmatched";if(uncertain)badge=state=="unmatched"?L"未匹配":L"匹配待确认";else if(state=="matched"&&!reviewed)badge=L"匹配粗轴";}
        if(locked)badge=L"已保护";
        if((filter==1&&reviewed)||(filter==2&&!uncertain)||(filter==3&&!locked))continue;
        if(!query.empty()&&!(text+reading+show(studio_document::text(value,"romaji"))).Lower().Contains(query))continue;
        auto stamp=[](int ms){return wxString::Format(L"%02d:%02d.%02d",ms/60000,ms/1000%60,ms/10%100);};
        cards.push_back({line.Id,line.Row+1,text,reading,stamp(int(line.Start))+L"  —  "+stamp(int(line.End)),badge,locked,reviewed,uncertain});
    }
    SetItemCount(cards.size());empty_hint->SetLabel(query.empty()&&filter==0?L"还没有歌词\n点击下方粘贴，每行一句\n已有 ASS / JSON 也可直接拖入":L"没有符合条件的歌词\n清除搜索或换一个筛选条件");empty_hint->Show(cards.empty());syncing=false;SyncSelection();Refresh();
}
int StudioLyrics::IdAt(size_t index)const{return index<cards.size()?cards[index].id:-1;}
void StudioLyrics::SyncSelection(){
    syncing=true;DeselectAll();auto selected=context->selectionController->GetSelectedSet();auto active=context->selectionController->GetActiveLine();
    for(size_t i=0;i<cards.size();++i){for(auto line:selected)if(line->Id==cards[i].id){Select(i);break;}if(active&&active->Id==cards[i].id)ScrollToRow(i);}
    syncing=false;Refresh();
}
void StudioLyrics::Choose(int index,bool extend){if(index<0||index>=int(cards.size()))return;if(!extend)DeselectAll();Select(index);ApplySelection(index);}
void StudioLyrics::ApplySelection(int index){
    if(index<0||index>=int(cards.size()))return;
    if(!context->studioPanel->FlushChanges()){SyncSelection();return;}
    Selection selected;AssDialogue *active=nullptr;
    for(size_t i=0;i<cards.size();++i)if(IsSelected(i))for(auto& line:context->ass->Events)if(line.Id==cards[i].id){selected.insert(&line);if(int(i)==index)active=&line;break;}
    if(!active){SyncSelection();return;}context->selectionController->SetSelectionAndActive(selected,active);
    if(context->project->VideoProvider())context->videoController->JumpToTime(active->Start);
}
wxCoord StudioLyrics::OnMeasureItem(size_t)const{return FromDIP(112);}
void StudioLyrics::OnDrawBackground(wxDC& dc,wxRect const& rect,size_t)const{dc.SetPen(*wxTRANSPARENT_PEN);dc.SetBrush(*wxWHITE_BRUSH);dc.DrawRectangle(rect);}
void StudioLyrics::OnDrawItem(wxDC& dc,wxRect const& outer,size_t index)const{
    if(index>=cards.size())return;auto const& card=cards[index];auto rect=outer;rect.Deflate(FromDIP(8),FromDIP(5));bool selected=IsSelected(index);
    dc.SetPen(wxPen(selected?wxColour(166,185,244):wxColour(225,231,241)));dc.SetBrush(wxBrush(selected?studio_ui::tint:wxColour(250,251,254)));dc.DrawRoundedRectangle(rect,FromDIP(10));
    int x=rect.x+FromDIP(13),y=rect.y+FromDIP(12),width=rect.width-FromDIP(26);
    dc.SetFont(studio_ui::font(8));dc.SetTextForeground(muted);dc.DrawText(wxString::Format(L"%02d   ",card.row)+card.time,x,y);
    dc.SetFont(studio_ui::font(11,true));dc.SetTextForeground(ink);dc.DrawText(clipped(dc,card.text,width),x,y+FromDIP(23));
    dc.SetFont(studio_ui::font(8.5));dc.SetTextForeground(muted);dc.DrawText(clipped(dc,card.reading.empty()?wxString(L"添加注音，让每个字都能跟唱"):card.reading,width),x,y+FromDIP(49));
    auto badge_colour=card.uncertain?wxColour(164,105,22):card.reviewed?wxColour(24,124,98):accent;
    auto badge_background=card.uncertain?wxColour(255,246,225):card.reviewed?wxColour(229,247,239):wxColour(232,237,255);
    dc.SetFont(studio_ui::font(8));auto badge_size=dc.GetTextExtent(card.badge);dc.SetPen(*wxTRANSPARENT_PEN);dc.SetBrush(wxBrush(badge_background));dc.DrawRoundedRectangle(x,y+FromDIP(70),badge_size.x+FromDIP(14),FromDIP(20),FromDIP(5));dc.SetTextForeground(badge_colour);dc.DrawText(card.badge,x+FromDIP(7),y+FromDIP(72));
    if(selected){dc.SetPen(*wxTRANSPARENT_PEN);dc.SetBrush(wxBrush(accent));dc.DrawRoundedRectangle(rect.x,rect.y+FromDIP(16),FromDIP(3),rect.height-FromDIP(32),2);}
}
void StudioLyrics::RenderCards(wxDC& dc)const{dc.SetBackground(*wxWHITE_BRUSH);dc.Clear();for(size_t i=0;i<cards.size();++i){auto rect=GetItemRect(i);if(!rect.IsEmpty()){OnDrawBackground(dc,rect,i);OnDrawItem(dc,rect,i);}}}

StudioShell::StudioShell(wxWindow *parent,agi::Context *c):wxPanel(parent),context(c){
    SetBackgroundColour(canvas);SetForegroundColour(ink);SetFont(studio_ui::font());
    auto root=new wxBoxSizer(wxVERTICAL);auto header=new wxPanel(this);header->SetBackgroundColour(studio_ui::header);header->SetFont(studio_ui::font());auto bar=new wxBoxSizer(wxHORIZONTAL);
    auto brand=studio_ui::label(header,L"声稿",16,*wxWHITE,true);bar->Add(brand,0,wxALIGN_CENTER_VERTICAL|wxLEFT|wxRIGHT,20);
    auto product=studio_ui::label(header,L"KARAOKE STUDIO",8.5,wxColour(151,167,196));bar->Add(product,0,wxALIGN_CENTER_VERTICAL|wxRIGHT,20);
    auto project=button(header,L"项目 ▾",[this]{auto value=menu::GetMenu("main/file",wxID_HIGHEST+21000,context);menu::OpenPopupMenu(value.get(),this);},false,76);bar->Add(project,0,wxALIGN_CENTER_VERTICAL|wxRIGHT,10);
    project_label=studio_ui::label(header,L"未命名工程",9,wxColour(192,203,223));project_label->SetMinSize(wxSize(0,-1));project_label->SetForegroundColour(wxColour(192,203,223));bar->Add(project_label,1,wxALIGN_CENTER_VERTICAL|wxLEFT|wxRIGHT,8);
    undo=button(header,L"撤销",[this]{if(context->studioPanel->FlushChanges())context->subsController->Undo();},false,52);redo=button(header,L"重做",[this]{if(context->studioPanel->FlushChanges())context->subsController->Redo();},false,52);bar->Add(undo,0,wxALIGN_CENTER_VERTICAL|wxRIGHT,4);bar->Add(redo,0,wxALIGN_CENTER_VERTICAL|wxRIGHT,12);
    bar->Add(button(header,L"工具 ▾",[this]{Tools();},false,76),0,wxALIGN_CENTER_VERTICAL|wxRIGHT,12);
    bar->Add(button(header,L"保存工程",[this]{cmd::call("subtitle/save",context);},true,94),0,wxALIGN_CENTER_VERTICAL|wxRIGHT,16);
    bar->Add(button(header,L"—",[this]{context->frame->Iconize();},false,38),0,wxALIGN_CENTER_VERTICAL|wxRIGHT,3);
    maximize=button(header,L"□",[this]{ToggleMaximize();},false,38);maximize->SetToolTip(L"最大化 / 还原");bar->Add(maximize,0,wxALIGN_CENTER_VERTICAL|wxRIGHT,3);
    auto close=button(header,L"×",[this]{context->frame->Close();},false,38);close->SetToolTip(L"关闭（检查未保存改动）");bar->Add(close,0,wxALIGN_CENTER_VERTICAL|wxRIGHT,10);
    header->SetSizer(bar);header->SetMinSize(FromDIP(wxSize(0,64)));root->Add(header,0,wxEXPAND);root->Add(studio_ui::rule(this,studio_ui::header_line),0,wxEXPAND);
    auto drag=[this](wxMouseEvent& event){
#ifdef _WIN32
        if(event.LeftDown()){
            auto window=static_cast<wxWindow*>(event.GetEventObject());auto point=window->ClientToScreen(event.GetPosition());auto hwnd=static_cast<HWND>(context->frame->GetHandle());
            auto hit=::SendMessageW(hwnd,WM_NCHITTEST,0,MAKELPARAM(point.x,point.y));
            ::ReleaseCapture();::SendMessageW(hwnd,WM_NCLBUTTONDOWN,hit>=HTLEFT&&hit<=HTBOTTOMRIGHT?hit:HTCAPTION,MAKELPARAM(point.x,point.y));
        }
#else
        event.Skip();
#endif
    };
    for(wxWindow *item:std::vector<wxWindow*>{header,brand,product,project_label}){item->Bind(wxEVT_LEFT_DOWN,drag);item->Bind(wxEVT_LEFT_DCLICK,[this](wxMouseEvent&){ToggleMaximize();});}
#ifdef _WIN32
    // Expose a small resize gutter on the shell; it shares the canvas colour.
    Bind(wxEVT_LEFT_DOWN,[this,drag](wxMouseEvent& event){auto point=ClientToScreen(event.GetPosition());auto hwnd=static_cast<HWND>(context->frame->GetHandle());auto hit=::SendMessageW(hwnd,WM_NCHITTEST,0,MAKELPARAM(point.x,point.y));if(hit>=HTLEFT&&hit<=HTBOTTOMRIGHT)drag(event);else event.Skip();});
    Bind(wxEVT_MOTION,[this](wxMouseEvent& event){auto point=ClientToScreen(event.GetPosition());auto hit=::SendMessageW(static_cast<HWND>(context->frame->GetHandle()),WM_NCHITTEST,0,MAKELPARAM(point.x,point.y));SetCursor(wxCursor(hit==HTLEFT||hit==HTRIGHT?wxCURSOR_SIZEWE:hit==HTTOP||hit==HTBOTTOM?wxCURSOR_SIZENS:hit==HTTOPLEFT||hit==HTBOTTOMRIGHT?wxCURSOR_SIZENWSE:hit==HTTOPRIGHT||hit==HTBOTTOMLEFT?wxCURSOR_SIZENESW:wxCURSOR_ARROW));event.Skip();});
#endif
    body=new wxPanel(this);body->SetBackgroundColour(canvas);root->Add(body,1,wxEXPAND|wxLEFT|wxRIGHT|wxBOTTOM,FromDIP(6));SetSizer(root);
}
void StudioShell::Attach(wxWindow *left,wxWindow *center,wxWindow *editor){
    advanced=editor;editing=center;advanced->Hide();
    auto left_layout=new wxBoxSizer(wxVERTICAL);auto title=studio_ui::label(left,L"歌词库",13,ink,true);left_layout->Add(title,0,wxALL,16);
    search=new wxTextCtrl(left,wxID_ANY);search->SetHint(L"搜索原文 / 假名 / 罗马音");search->SetMinSize(wxSize(0,FromDIP(30)));studio_ui::field(search);left_layout->Add(search,0,wxEXPAND|wxLEFT|wxRIGHT|wxBOTTOM,12);
    filter=new wxChoice(left,wxID_ANY);for(auto label:{L"全部歌词",L"时间尚未确认",L"匹配需要确认",L"已保护"})filter->Append(label);filter->SetSelection(0);filter->SetMinSize(wxSize(0,-1));studio_ui::field(filter);left_layout->Add(filter,0,wxEXPAND|wxLEFT|wxRIGHT|wxBOTTOM,12);
    left_layout->Add(studio_ui::rule(left),0,wxEXPAND|wxLEFT|wxRIGHT,14);lyrics=new StudioLyrics(left,context);left_layout->Add(lyrics,1,wxEXPAND);count_label=studio_ui::label(left,L"还没有歌词",8.5,muted);count_label->SetForegroundColour(muted);left_layout->Add(count_label,0,wxLEFT|wxRIGHT|wxTOP,14);
    left_layout->Add(button(left,L"＋ 粘贴普通歌词",[this]{context->studioPanel->PasteLyrics();},true),0,wxEXPAND|wxALL,12);left->SetSizer(left_layout);
    auto filtered=[this](wxCommandEvent&){lyrics->SetFilter(search->GetValue(),filter->GetSelection());UpdateState();};search->Bind(wxEVT_TEXT,filtered);filter->Bind(wxEVT_CHOICE,filtered);
    BindConnection(context->ass->AddCommitListener([this](int,AssDialogue const*){UpdateState();}));BindConnection(context->selectionController->AddActiveLineListener([this](AssDialogue*){UpdateState();}));
    BindConnection(context->subsController->AddFileSaveListener([this]{UpdateState();}));BindConnection(context->subsController->AddFileOpenListener([this]{UpdateState();}));
    BindConnection(context->project->AddVideoProviderListener([this](AsyncVideoProvider*){CallAfter([this]{FitVideo();});}));
    // Insert the compact current-line card above the optional advanced editor.
    auto inspector=new StudioSurface(center);inspector->SetBackgroundColour(studio_ui::soft);auto layout=new wxBoxSizer(wxHORIZONTAL);auto description=new wxBoxSizer(wxVERTICAL);
    current_time=studio_ui::label(inspector,L"当前歌词",8.5,muted);current_time->SetForegroundColour(muted);description->Add(current_time,0,wxBOTTOM,6);current_text=studio_ui::label(inspector,L"添加视频，然后粘贴普通歌词开始制作",11,ink,true);current_text->SetMinSize(wxSize(0,-1));description->Add(current_text,0,wxEXPAND);
    guide_hint=studio_ui::label(inspector,L"每次完成一步，这里会提示接下来做什么。",8.5,muted);guide_hint->SetName("workflow-next-hint");guide_hint->SetMinSize(wxSize(0,FromDIP(17)));guide_hint->SetWindowStyleFlag(wxST_ELLIPSIZE_END);description->Add(guide_hint,0,wxEXPAND|wxTOP,6);
    layout->Add(description,1,wxALIGN_CENTER_VERTICAL|wxALL,14);auto actions=new wxBoxSizer(wxVERTICAL);next_step=button(inspector,L"添加视频或音频",[this]{context->studioPanel->DoNextStep();},true,152);next_step->SetName("workflow-next-action");actions->Add(next_step,0,wxEXPAND|wxBOTTOM,6);actions->Add(button(inspector,L"编辑原文 / 时间",[this]{context->studioPanel->EditCurrent();},false,152),0,wxEXPAND);layout->Add(actions,0,wxALIGN_CENTER_VERTICAL|wxALL,10);inspector->SetSizer(layout);center->GetSizer()->Insert(1,inspector,0,wxEXPAND|wxBOTTOM,10);
    center->GetSizer()->Add(advanced,0,wxEXPAND|wxTOP,8);center->GetSizer()->Hide(advanced);
    context->frame->Bind(wxEVT_SIZE,[this](wxSizeEvent& event){event.Skip();CallAfter([this]{FitVideo();});});UpdateState();
}
void StudioShell::UpdateState(){
    if(layout_mode)layout_mode->SetSelection(!context->frame->IsAudioShown()?2:!context->frame->IsVideoShown()?1:0);
    if(next_step){auto step=context->studioPanel->NextStep();next_step->SetLabel(step.first);next_step->Enable(step.second!=8);wxString hints[]={L"第1步 · 拖入媒体，或点右侧按钮选择文件",L"第2步 · 正确歌词每行一句，无需时间标签",L"自动结果还没写入工程，先查看再应用",L"本地词典生成分词，先审核；不联网",L"按假名分演唱音节，时间仍需试听校准",L"第3步 · 听边界，拖动，再确认下一行",L"第4步 · 补读音；DeepSeek 可选",L"第5步 · 先检查与预览，再导出 ASS",L"处理完成后，点击“审核结果”继续"};guide_hint->SetLabel(hints[step.second]);guide_hint->SetToolTip(hints[step.second]);}
    auto filename=wxString(context->subsController->Filename().filename().wstring());if(filename.size()>35)filename=filename.Left(35)+L"…";project_label->SetLabel((context->subsController->IsModified()?L"●  ":L"✓  ")+filename);undo->Enable(!context->subsController->IsUndoStackEmpty());redo->Enable(!context->subsController->IsRedoStackEmpty());
    if(count_label){size_t total=0;for(auto const& line:context->ass->Events)if(!line.Comment&&!line.GetStrippedText().empty())++total;count_label->SetLabel(wxString::Format(L"显示 %zu 行  ·  共 %zu 行",lyrics->GetItemCount(),total));}
    if(current_text){auto line=context->selectionController->GetActiveLine();if(line){auto value=context->studioPanel->DescribeLine(line);auto const& object=static_cast<json::Object const&>(value);auto text=show(studio_document::text(object,"text"));current_text->SetToolTip(text);int limit=std::max(12,(editing->GetClientSize().x-FromDIP(180))/FromDIP(14));if(int(text.size())>limit)text=text.Left(limit)+L"…";text.Replace(L"\n",L" / ");current_text->SetLabel(text.empty()?wxString(L"添加媒体，再粘贴原歌词"):text);current_time->SetLabel(text.empty()?wxString(L"从这里开始"):wxString::Format(L"第 %d 行  ·  %d → %d ms",line->Row+1,int(line->Start),int(line->End)));}else{current_time->SetLabel(L"当前歌词");current_text->SetLabel(L"先添加媒体和普通歌词");}}
    Layout();
}
void StudioShell::ToggleMaximize(){context->frame->Maximize(!context->frame->IsMaximized());maximize->SetLabel(context->frame->IsMaximized()?L"❐":L"□");}
void StudioShell::ToggleAdvanced(){if(!advanced)return;advanced->Show(!advanced->IsShown());editing->GetSizer()->Show(advanced,advanced->IsShown());editing->Layout();if(auto scroll=dynamic_cast<wxScrolledWindow*>(editing)){scroll->FitInside();if(!advanced->IsShown())scroll->Scroll(0,0);}}
void StudioShell::Tools(){
    wxMenu popup;popup.Append(9001,L"高级字幕编辑区");auto add=[&](char const *name,wxString const& label,int id){auto value=menu::GetMenu(name,wxID_HIGHEST+id,context);popup.AppendSubMenu(value.release(),label);};
    add("main/subtitle",L"字幕与样式",41000);add("main/timing",L"时间工具",42000);add("main/audio",L"音频工具",43000);add("main/video",L"视频工具",44000);add("main/edit",L"编辑与查找",45000);add("main/view",L"视图与设置",46000);
    popup.Bind(wxEVT_MENU,[this](wxCommandEvent&){ToggleAdvanced();},9001);menu::OpenPopupMenu(&popup,this);
}
void StudioShell::FitVideo(){
    if(fitting||!editing||!context->project->VideoProvider()||!context->frame->IsVideoShown())return;
    fitting=true;auto provider=context->project->VideoProvider();auto display=context->videoDisplay;
    int width=std::max(100,editing->GetClientSize().x-FromDIP(16)),available=editing->GetClientSize().y;
    int wanted=OPT_GET("Audio/Display Height")->GetInt()+(context->karaoke->IsEnabled()?context->karaoke->GetSize().y+6:0);
    if(context->audioBox->IsShown())context->audioBox->SetMinSize(wxSize(0,wanted));
    auto reserved=[&]{return std::max(0,editing->GetSizer()->GetMinSize().y-std::max(0,display->GetMinSize().y));};
    int minimum_video=std::max(1,int(provider->GetHeight()*.125)),fixed=reserved();
    int shortage=fixed+minimum_video+FromDIP(8)-available;
    if(shortage>0&&context->audioBox->IsShown()){
        context->audioBox->SetMinSize(wxSize(0,std::max(FromDIP(120),wanted-shortage)));fixed=reserved();
    }
    int height=std::max(minimum_video,available-fixed-FromDIP(8));
    double zoom=std::min(double(width)/provider->GetWidth(),double(height)/provider->GetHeight());zoom=std::clamp(zoom,.125,1.5);auto viewport=context->videoDisplay->GetClientSize();if(std::abs(context->videoDisplay->GetWindowZoom()-zoom)>.005||viewport.x<=2||viewport.y<=2)context->videoDisplay->SetWindowZoom(zoom);editing->Layout();if(auto scroll=dynamic_cast<wxScrolledWindow*>(editing))scroll->FitInside();UpdateState();fitting=false;
}
bool StudioShell::CurrentEditorFits()const{if(!current_text||!editing)return false;auto panel=current_text->GetParent();auto origin=editing->ScreenToClient(panel->ClientToScreen(wxPoint(0,0)));return origin.y>=0&&origin.y+panel->GetSize().y<=editing->GetClientSize().y;}
bool StudioShell::TransportFits()const{if(!transport||!editing)return false;auto origin=editing->ScreenToClient(transport->ClientToScreen(wxPoint(0,0)));auto size=transport->GetSize();return origin.x>=0&&origin.y>=0&&origin.x+size.x<=editing->GetClientSize().x&&origin.y+size.y<=editing->GetClientSize().y;}
void StudioShell::SetView(int mode){if(mode<0||mode>2)return;context->frame->SetDisplayMode(mode==1?0:1,mode==2?0:1);FitVideo();UpdateState();}
wxPanel *StudioShell::Transport(wxWindow *parent){
    auto panel=new StudioSurface(parent);transport=panel;panel->SetBackgroundColour(studio_ui::soft);auto layout=new wxBoxSizer(wxHORIZONTAL);auto view=new wxBoxSizer(wxHORIZONTAL);
    layout->Add(button(panel,L"▶",[this]{cmd::call("audio/play/selection",context);},true,38),0,wxRIGHT,6);
    layout->Add(button(panel,L"■",[this]{context->studioPanel->StopAudition();},false,38),0,wxRIGHT,8);
    auto mode=new wxChoice(panel,wxID_ANY);mode->SetName("audio-view-mode");studio_ui::field(mode);for(auto label:{L"柔和波形",L"传统波形",L"频谱"})mode->Append(label);mode->SetSelection(OPT_GET("Audio/Spectrum")->GetBool()?2:OPT_GET("Colour/Audio Display/Waveform")->GetString()=="Icy Blue"?0:1);mode->Bind(wxEVT_CHOICE,[mode](wxCommandEvent&){int choice=mode->GetSelection();if(choice<2)OPT_SET("Colour/Audio Display/Waveform")->SetString(choice==0?"Icy Blue":"Green");OPT_SET("Audio/Spectrum")->SetBool(choice==2);});view->Add(mode,0,wxALIGN_CENTER_VERTICAL|wxRIGHT,8);
    BindConnection(OPT_SUB("Audio/Spectrum",[mode](agi::OptionValue const& option){mode->SetSelection(option.GetBool()?2:OPT_GET("Colour/Audio Display/Waveform")->GetString()=="Icy Blue"?0:1);}));
    auto rate=new wxChoice(panel,wxID_ANY);studio_ui::field(rate);for(auto label:{L"0.5×",L"0.75×",L"1.0×"})rate->Append(label);rate->SetSelection(2);rate->SetToolTip(L"慢放会改变音高");rate->Bind(wxEVT_CHOICE,[this,rate](wxCommandEvent&){double speeds[]={.5,.75,1.};context->audioController->SetPlaybackRate(speeds[rate->GetSelection()]);});layout->Add(rate,0,wxALIGN_CENTER_VERTICAL|wxRIGHT,8);
    view->Add(button(panel,L"逐词校对",[this]{context->karaoke->SetEnabled(true);context->studioPanel->GoToStage(1);context->studioPanel->FocusTiming();},false,84),0,wxRIGHT,8);
    view->Add(button(panel,L"定位本行",[this]{context->studioPanel->FocusTiming();},false,84),0,wxRIGHT,8);
    layout_mode=new wxChoice(panel,wxID_ANY);layout_mode->SetName("workspace-view");for(auto label:{L"制作视图",L"专注打轴",L"放大预览"})layout_mode->Append(label);layout_mode->SetSelection(0);studio_ui::field(layout_mode);layout_mode->SetToolTip(L"专注打轴隐藏视频；放大预览隐藏时间轴，导出前看清注音效果。");layout_mode->Bind(wxEVT_CHOICE,[this](wxCommandEvent& e){SetView(e.GetSelection());});view->Add(layout_mode,0,wxALIGN_CENTER_VERTICAL);
    playback_time=studio_ui::label(panel,L"00:00.00",8.5,muted);playback_time->SetToolTip(L"当前播放位置");layout->AddStretchSpacer();layout->Add(playback_time,0,wxALIGN_CENTER_VERTICAL|wxLEFT,10);
    auto update_time=[this](int time){if(playback_time)playback_time->SetLabel(wxString::Format(L"%02d:%02d.%02d",time/60000,time/1000%60,time/10%100));};
    BindConnection(context->videoController->AddSeekListener([this,update_time]{if(context->project->VideoProvider())update_time(context->videoController->TimeAtFrame(context->videoController->GetFrameN()));}));
    BindConnection(context->audioController->AddPlaybackPositionListener(update_time));
    auto controls=new wxBoxSizer(wxHORIZONTAL);
    auto slider=[&](wxString const& label,char const *option,int minimum,int maximum,std::function<void(int)> change){
        auto column=new wxBoxSizer(wxVERTICAL);column->Add(studio_ui::label(panel,label,8.5,muted),0,wxBOTTOM,3);
        auto track=new wxSlider(panel,wxID_ANY,OPT_GET(option)->GetInt(),minimum,maximum,wxDefaultPosition,FromDIP(wxSize(0,22)),wxSL_HORIZONTAL);
        track->SetMinSize(FromDIP(wxSize(0,22)));track->SetBackgroundColour(studio_ui::soft);track->SetToolTip(label);
        BindConnection(OPT_SUB(option,[track](agi::OptionValue const& value){track->SetValue(value.GetInt());}));
        track->Bind(wxEVT_SLIDER,[change](wxCommandEvent& event){change(event.GetInt());});column->Add(track,0,wxEXPAND);controls->Add(column,1,wxRIGHT,8);
    };
    slider(L"横向缩放","Audio/Zoom/Horizontal",-30,50,[this](int value){context->audioBox->StudioSetHorizontalZoom(value);});
    slider(L"波形高度","Audio/Zoom/Vertical",0,100,[this](int value){context->audioBox->StudioSetAmplitude(value);});
    slider(L"音量","Audio/Volume",0,100,[this](int value){context->audioBox->StudioSetVolume(value);});
    auto padded=new wxBoxSizer(wxVERTICAL);padded->Add(layout,0,wxEXPAND|wxALL,10);padded->Add(view,0,wxEXPAND|wxLEFT|wxRIGHT|wxBOTTOM,10);padded->Add(studio_ui::rule(panel),0,wxEXPAND|wxLEFT|wxRIGHT,10);padded->Add(controls,0,wxEXPAND|wxALL,10);panel->SetSizer(padded);return panel;
}
