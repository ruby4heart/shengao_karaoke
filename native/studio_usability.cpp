// Copyright (c) 2026 Shengao Karaoke Studio contributors. MIT.
#include "studio_panel.h"
#include "studio_pauses.h"
#include "ass_dialogue.h"
#include "ass_file.h"
#include "audio_controller.h"
#include "audio_karaoke.h"
#include "include/aegisub/context.h"
#include "project.h"
#include "selection_controller.h"
#include "time_range.h"
#include <libaegisub/audio/provider.h>
#include <wx/button.h>
#include <wx/checkbox.h>
#include <wx/checklst.h>
#include <wx/choice.h>
#include <wx/dialog.h>
#include <wx/sizer.h>
#include <wx/spinctrl.h>
#include <wx/stattext.h>
#include <wx/stdpaths.h>
#include <wx/textctrl.h>
#include <map>

namespace {
wxString show(std::string const& text){return wxString::FromUTF8(text);}
wxString clock(int ms){return wxString::Format(L"%02d:%02d.%02d",ms/60000,ms/1000%60,ms/10%100);}
void wrap(wxStaticText* label,int width){auto original=label->GetLabel();wxString out;int used=0;for(auto point:original){if(point=='\n'){out+='\n';used=0;continue;}int size=label->GetTextExtent(wxString(point)).x;if(used&&used+size>width){out+='\n';used=0;}out+=point;used+=size;}label->SetLabel(out);label->SetMinSize(wxSize(0,-1));}
}

std::pair<wxString,int> StudioPanel::NextStep(){
    if(pid)return {L"正在处理…",8};
    if(has_pending_result)return {L"审核自动结果",2};
    if(!context->project->AudioProvider()&&!context->project->VideoProvider())return {L"添加视频或音频",0};
    auto rows=ReadLines(false);if(rows.empty())return {L"粘贴普通歌词",1};
    bool words=false,mora=false,reading=false,unreviewed=false;
    for(auto const& value:rows){auto const& row=static_cast<json::Object const&>(value);auto const& list=static_cast<json::Array const&>(row.at("units"));
        if(studio_pauses::locked(value))continue;auto review=row.find("reviewed");bool confirmed=review!=row.end()&&static_cast<json::Boolean const&>(review->second);words|=list.empty()&&!confirmed;unreviewed|=!confirmed;
        for(auto const& part:list){auto const& unit=static_cast<json::Object const&>(part);mora|=!confirmed&&studio_workflow::needs_mora(part);reading|=studio_workflow::kanji(studio_document::text(unit,"text"))&&studio_document::text(unit,"kana").empty();}
    }
    if(words)return {L"生成分词初稿",3};
    if(mora&&unreviewed)return {L"拆出演唱音节",4};
    if(unreviewed)return {L"试听并校准时间",5};
    if(reading)return {L"补全假名读音",6};
    return {L"检查并导出字幕",7};
}
void StudioPanel::DoNextStep(){
    if(!FlushChanges())return;auto step=NextStep().second;if(step==8){SetStatus(L"正在处理，完成后点击“审核结果”；当前可继续试听和校轴。");return;}
    if(step==0){OpenMedia();return;}if(step==1){ImportLyrics();return;}if(step==2){ReviewPending();return;}
    if(step==3||step==4){LocalSegment(step==3?"words":"mora",true);return;}
    if(step==5){auto active=context->selectionController->GetActiveLine();bool ready=false;if(active){auto data=ReadLine(active);auto const& row=static_cast<json::Object const&>(data);auto review=row.find("reviewed");ready=!studio_pauses::locked(data)&&(review==row.end()||!static_cast<json::Boolean const&>(review->second));}if(!ready)for(auto& row:context->ass->Events){auto data=ReadLine(&row);auto const& object=static_cast<json::Object const&>(data);auto review=object.find("reviewed");if(!studio_document::text(object,"text").empty()&&!studio_pauses::locked(data)&&(review==object.end()||!static_cast<json::Boolean const&>(review->second))){SelectLine(row.Id);break;}}ShowStage(1);context->karaoke->SetEnabled(true);FocusTiming();SetStatus(L"从左侧选一句，先听起点和终点，拖边界后点“确认 → 下一行”。停顿可在“停顿处理”中保留或合并。");return;}
    ShowStage(step==6?2:3);
}

void StudioPanel::BeginnerGuide(std::function<int(wxDialog&)> const& inspect){
    wxDialog dialog(this,wxID_ANY,L"第一次使用 · 五步做出卡拉 OK 字幕",wxDefaultPosition,FromDIP(wxSize(650,570)),wxDEFAULT_DIALOG_STYLE|wxRESIZE_BORDER);dialog.SetMinSize(FromDIP(wxSize(620,540)));dialog.SetFont(studio_ui::font());dialog.SetBackgroundColour(studio_ui::paper);auto box=new wxBoxSizer(wxVERTICAL);
    auto text=[&](wxString const& value,bool heading=false){auto label=studio_ui::label(&dialog,value,heading?11:9.5,heading?studio_ui::ink:studio_ui::muted,heading);wrap(label,FromDIP(580));box->Add(label,0,wxEXPAND|wxLEFT|wxRIGHT|wxBOTTOM,16);};
    box->AddSpacer(18);text(L"先准备：一个视频／音频 ＋ 每行一句的原歌词",true);
    text(L"1  导入素材\n拖入媒体，再粘贴歌词。已有 ASS / JSON 工程可直接打开，不必重做。");
    text(L"2  得到初稿\n有 API 可转录并匹配原歌词；也可离线生成分词，自己打时间。自动结果先审核，应用后才能继续。");
    text(L"3  听一句，校一句\n“逐词校对”开启打 K。拖绿／蓝两端及中间边界；听起点／终点，确认后进入下一行。停顿可保留或并入相邻音节。");
    text(L"4  检查日语读音\n注音页修改假名，用 | 分音节（きょ|う）；“二次分析”结合转录复核，DeepSeek 为可选联网功能。");
    text(L"5  保存与导出\nCtrl+S 保存可编辑工程；导出页先检查与预览，再导出成品 ASS。SRT / TXT 不保留卡拉 OK 高亮。");
    text(L"快捷键：F6 定位 · Ctrl+Enter 确认下一行 · Esc 停止\n页面中央的“下一步”会随进度改变；此指南可随时重新打开。");
    auto row=new wxBoxSizer(wxHORIZONTAL);auto demo=new wxButton(&dialog,1001,L"用离线示例练习");demo->SetName("guide-demo");demo->Bind(wxEVT_BUTTON,[&](wxCommandEvent&){dialog.EndModal(1001);});row->Add(demo,0,wxRIGHT,10);auto next=new wxButton(&dialog,1002,L"去做下一步");next->SetName("guide-next");next->Bind(wxEVT_BUTTON,[&](wxCommandEvent&){dialog.EndModal(1002);});row->Add(next,0);box->AddStretchSpacer();box->Add(row,0,wxLEFT|wxRIGHT|wxBOTTOM,16);box->Add(dialog.CreateButtonSizer(wxCLOSE),0,wxEXPAND|wxLEFT|wxRIGHT|wxBOTTOM,16);dialog.SetSizer(box);
    int answer=inspect?inspect(dialog):dialog.ShowModal();if(answer==1002){DoNextStep();return;}if(answer==1001){auto executable=std::filesystem::path(wxStandardPaths::Get().GetExecutablePath().ToStdWstring());auto path=executable.parent_path()/"demo/tutorial.json";if(!std::filesystem::exists(path))path=executable.parent_path().parent_path().parent_path()/"demo/tutorial.json";if(!OpenProject(path))return;context->project->CloseVideo();ShowStage(1);context->karaoke->SetEnabled(true);FocusTiming();SetStatus(L"示例是合成音调和人工歌词，用于熟悉校轴，不需要 API。先试“听起点”，再拖边界；Ctrl+Z 撤销。");}
}

void StudioPanel::PauseDialog(std::function<int(wxDialog&)> const& inspect){
    if(!FlushChanges())return;
    wxDialog dialog(this,wxID_ANY,L"停顿处理 · 保留或合并到相邻音节",wxDefaultPosition,FromDIP(wxSize(760,650)),wxDEFAULT_DIALOG_STYLE|wxRESIZE_BORDER);dialog.SetMinSize(FromDIP(wxSize(700,600)));dialog.SetFont(studio_ui::font());dialog.SetBackgroundColour(studio_ui::paper);auto box=new wxBoxSizer(wxVERTICAL);
    auto note=studio_ui::label(&dialog,L"停顿是没有歌词高亮的时间。合并会让前一音节唱得更久，或让后一音节更早开始；不会合并文字。先试听，选择需要处理的空段，再应用。",9.5,studio_ui::muted);wrap(note,FromDIP(690));box->Add(note,0,wxEXPAND|wxALL,16);
    auto scope=new wxChoice(&dialog,wxID_ANY);for(auto s:{L"当前这一行",L"左侧选中的行",L"全部歌词"})scope->Append(s);scope->SetSelection(0);scope->SetName("pauses-scope");box->Add(scope,0,wxEXPAND|wxLEFT|wxRIGHT|wxBOTTOM,16);
    auto policy=new wxChoice(&dialog,wxID_ANY);for(auto s:{L"保留停顿（不改时间）",L"并入前一音节 · 延长前一个字",L"并入后一音节 · 下一个字提前"})policy->Append(s);policy->SetSelection(0);policy->SetName("pauses-policy");box->Add(policy,0,wxEXPAND|wxLEFT|wxRIGHT|wxBOTTOM,16);
    auto edges=new wxCheckBox(&dialog,wxID_ANY,L"也列出整行开头／结尾的空白（默认保留）");edges->SetName("pauses-edges");box->Add(edges,0,wxLEFT|wxRIGHT|wxBOTTOM,12);
    auto summary=studio_ui::label(&dialog,L"",9,studio_ui::muted);summary->SetName("pauses-summary");box->Add(summary,0,wxEXPAND|wxLEFT|wxRIGHT|wxBOTTOM,12);
    auto list=new wxCheckListBox(&dialog,wxID_ANY);list->SetName("pauses-list");list->SetMinSize(FromDIP(wxSize(0,150)));box->Add(list,1,wxEXPAND|wxLEFT|wxRIGHT|wxBOTTOM,16);
    auto outcome=new wxTextCtrl(&dialog,wxID_ANY,"",wxDefaultPosition,FromDIP(wxSize(-1,46)),wxTE_MULTILINE|wxTE_READONLY|wxBORDER_NONE);outcome->SetName("pauses-outcome");outcome->SetBackgroundColour(studio_ui::soft);outcome->SetForegroundColour(studio_ui::ink);outcome->SetMinSize(FromDIP(wxSize(0,46)));box->Add(outcome,0,wxEXPAND|wxLEFT|wxRIGHT|wxBOTTOM,12);
    auto selections=new wxBoxSizer(wxHORIZONTAL);auto threshold=new wxSpinCtrl(&dialog,wxID_ANY,"",wxDefaultPosition,FromDIP(wxSize(100,30)),wxSP_ARROW_KEYS,0,60000,120);threshold->SetName("pauses-threshold");selections->Add(threshold,0,wxRIGHT,6);auto short_only=new wxButton(&dialog,wxID_ANY,L"勾选 ≤ 此毫秒");selections->Add(short_only,0,wxRIGHT,8);auto all=new wxButton(&dialog,wxID_ANY,L"全选");selections->Add(all,0,wxRIGHT,8);auto none=new wxButton(&dialog,wxID_ANY,L"清空");selections->Add(none,0);box->Add(selections,0,wxEXPAND|wxLEFT|wxRIGHT|wxBOTTOM,16);
    auto actions=new wxBoxSizer(wxHORIZONTAL);auto play=new wxButton(&dialog,wxID_ANY,L"试听选中停顿前后");play->SetName("pauses-listen");auto stop=new wxButton(&dialog,wxID_ANY,L"停止");actions->Add(play,0,wxRIGHT,8);actions->Add(stop,0);box->Add(actions,0,wxLEFT|wxRIGHT|wxBOTTOM,16);
    auto explanation=studio_ui::label(&dialog,L"默认只勾选 ≤120ms 的内部短停顿；长停顿需主动勾选。锁定行／词跳过。合并后需重新确认时间，可 Ctrl+Z 撤销整次操作。",9,studio_ui::muted);wrap(explanation,FromDIP(690));box->Add(explanation,0,wxEXPAND|wxLEFT|wxRIGHT|wxBOTTOM,16);box->Add(dialog.CreateButtonSizer(wxOK|wxCANCEL),0,wxEXPAND|wxLEFT|wxRIGHT|wxBOTTOM,16);dialog.SetSizer(box);dialog.FindWindow(wxID_OK)->SetLabel(L"应用选择");
    struct Item {AssDialogue* line;json::UnknownElement before;int index;studio_pauses::Gap gap;};std::vector<Item> items;
    auto describe=[&]{int index=list->GetSelection();if(index<0||index>=int(items.size())){outcome->ChangeValue(L"当前范围没有可处理的停顿。可切换范围，或先生成并应用分词初稿。");return;}auto const& item=items[index];auto gap=item.gap;auto refs=studio_pauses::leaves(item.before);wxString message=L"当前空段："+clock(gap.start)+L" → "+clock(gap.end)+wxString::Format(L"（%dms）\n",gap.end-gap.start);int mode=policy->GetSelection();if(!mode)message+=L"应用后：保留现有停顿，时间不变。";else{bool previous=(mode==1&&gap.left>=0)||gap.right<0;auto ref=refs[previous?gap.left:gap.right];message+=L"应用后：「"+show(ref.text)+L"」"+(previous?L"结束延长至 ":L"开始提前至 ")+clock(previous?gap.end:gap.start)+L"；只处理已勾选的项。";}outcome->ChangeValue(message);};
    auto rebuild=[&]{items.clear();list->Clear();int skipped=0,lines=0;auto selected=context->selectionController->GetSelectedSet();auto active=context->selectionController->GetActiveLine();
        for(auto& line:context->ass->Events){if(line.Comment||(scope->GetSelection()==0 && &line!=active)||(scope->GetSelection()==1&&!selected.count(&line)))continue;auto value=ReadLine(&line);auto const& object=static_cast<json::Object const&>(value);if(studio_document::text(object,"text").empty())continue;if(studio_pauses::locked(value)){++skipped;continue;}++lines;auto gaps=studio_pauses::gaps(value,edges->GetValue());auto refs=studio_pauses::leaves(value);
            for(size_t i=0;i<gaps.size();++i){auto gap=gaps[i];wxString left=gap.left<0?wxString(L"行首"):show(refs[gap.left].text),right=gap.right<0?wxString(L"行尾"):show(refs[gap.right].text);list->Append(wxString::Format(L"第%d行  %s → %s  · %dms  · ",line.Row+1,clock(gap.start),clock(gap.end),gap.end-gap.start)+left+L" ｜ "+right);list->Check(items.size(),gap.left>=0&&gap.right>=0&&gap.end-gap.start<=threshold->GetValue());items.push_back({&line,studio_workflow::copy(value),int(i),gap});}
        }summary->SetLabel(wxString::Format(L"%d 行 · %zu 处停顿 · 跳过 %d 个锁定行；选择一项可试听。",lines,items.size(),skipped));if(!items.empty())list->SetSelection(0);play->Enable(!items.empty()&&context->project->AudioProvider());describe();};
    policy->Bind(wxEVT_CHOICE,[&](wxCommandEvent&){describe();});list->Bind(wxEVT_LISTBOX,[&](wxCommandEvent&){describe();});
    scope->Bind(wxEVT_CHOICE,[&](wxCommandEvent&){rebuild();});edges->Bind(wxEVT_CHECKBOX,[&](wxCommandEvent&){rebuild();});short_only->Bind(wxEVT_BUTTON,[&](wxCommandEvent&){for(size_t i=0;i<items.size();++i)list->Check(i,items[i].gap.left>=0&&items[i].gap.right>=0&&items[i].gap.end-items[i].gap.start<=threshold->GetValue());});all->Bind(wxEVT_BUTTON,[&](wxCommandEvent&){for(size_t i=0;i<items.size();++i)list->Check(i,true);});none->Bind(wxEVT_BUTTON,[&](wxCommandEvent&){for(size_t i=0;i<items.size();++i)list->Check(i,false);});
    bool played=false;play->Bind(wxEVT_BUTTON,[&](wxCommandEvent&){int index=list->GetSelection();auto provider=context->project->AudioProvider();if(index<0||!provider)return;int end=int(provider->GetNumSamples()*1000/provider->GetSampleRate());auto gap=items[index].gap;int a=std::max(0,gap.start-300),b=std::min(end,gap.end+300);if(b>a){StopAudition();context->audioController->PlayRange(TimeRange(a,b));played=true;}});stop->Bind(wxEVT_BUTTON,[&](wxCommandEvent&){StopAudition();});rebuild();
    int answer=inspect?inspect(dialog):dialog.ShowModal();if(played)StopAudition();if(answer!=wxID_OK||policy->GetSelection()==0)return;
    struct Pending {AssDialogue* line;json::UnknownElement value;};std::vector<Pending> pending;std::map<AssDialogue*,std::vector<int>> chosen;
    for(size_t i=0;i<items.size();++i)if(list->IsChecked(i))chosen[items[i].line].push_back(items[i].index);
    for(auto const& [line,indices]:chosen){auto entry=std::find_if(items.begin(),items.end(),[&](auto const& item){return item.line==line;});if(studio_workflow::encode(ReadLine(line))!=studio_workflow::encode(entry->before))throw std::runtime_error("歌词在处理期间已变化，请重新打开停顿处理");pending.push_back({line,studio_pauses::apply(entry->before,policy->GetSelection(),indices,edges->GetValue())});}
    for(auto const& entry:pending)WriteLine(entry.line,entry.value,true);
    if(!pending.empty()){context->ass->Commit(L"合并所选停顿",AssFile::COMMIT_DIAG_FULL|AssFile::COMMIT_EXTRADATA);RefreshLine();SetStatus(wxString::Format(L"已处理 %zu 行的所选停顿；文字及整行起止保持。请试听并重新确认时间，可撤销。",pending.size()));}else SetStatus(L"没有勾选停顿，工程保持不变。");
}
