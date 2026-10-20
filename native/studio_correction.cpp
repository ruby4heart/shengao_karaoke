// Copyright (c) 2026 Shengao Karaoke Studio contributors. MIT.
#include "studio_panel.h"
#include "studio_calibration.h"
#include "studio_pauses.h"
#include "ass_dialogue.h"
#include "ass_file.h"
#include "frame_main.h"
#include "audio_box.h"
#include "audio_display.h"
#include "audio_controller.h"
#include "audio_timing.h"
#include "audio_karaoke.h"
#include "include/aegisub/context.h"
#include "project.h"
#include "selection_controller.h"
#include "video_controller.h"
#include <libaegisub/audio/provider.h>
#include <wx/button.h>
#include <wx/checkbox.h>
#include <wx/choice.h>
#include <wx/dialog.h>
#include <wx/filedlg.h>
#include <wx/msgdlg.h>
#include <wx/sizer.h>
#include <wx/spinctrl.h>
#include <wx/stattext.h>
#include <wx/stdpaths.h>
#include <wx/textctrl.h>
#include <fstream>

namespace {
void wrap(wxStaticText *label,wxString const& original,int width){
    wxString result;int used=0;for(auto point:original){if(point=='\n'){result+='\n';used=0;continue;}wxString glyph(point);int next=label->GetTextExtent(glyph).x;if(used>0&&used+next>width){result+='\n';used=0;}result+=glyph;used+=next;}label->SetLabel(result);label->SetMinSize(wxSize(0,-1));
}
std::string text(json::Object const& value,char const *key){return studio_document::text(value,key);}
int ms(json::Object const& value,char const *key){return studio_document::time(value,key);}
json::Object const& object(json::UnknownElement const& value){return static_cast<json::Object const&>(value);}
json::UnknownElement file_json(std::filesystem::path const& file){std::ifstream in(file,std::ios::binary);if(!in)throw std::runtime_error("无法读取转录 JSON");return agi::json_util::parse(in);}
std::wstring normalized_path(std::filesystem::path const& path){auto value=std::filesystem::absolute(path).lexically_normal().wstring();std::transform(value.begin(),value.end(),value.begin(),::towlower);return value;}
}

void StudioPanel::BuildCalibration(wxWindow *parent,wxBoxSizer *layout){
    auto heading=new wxBoxSizer(wxHORIZONTAL);auto title=studio_ui::label(parent,L"人工校轴",10,studio_ui::ink,true);heading->Add(title,1,wxALIGN_CENTER_VERTICAL|wxRIGHT,6);pause_button=new StudioButton(parent,L"停顿处理",StudioButton::Kind::Secondary,wxSize(100,30));pause_button->SetName("timing-pauses");pause_button->Bind(wxEVT_BUTTON,[this](wxCommandEvent&){try{PauseDialog();}catch(std::exception const& error){SetStatus(wxString::FromUTF8(error.what()));}});heading->Add(pause_button,0,wxRIGHT,6);auto analyze=new StudioButton(parent,L"二次分析",StudioButton::Kind::Secondary,wxSize(84,30));analyze->SetName("timing-analyze");analyze->Bind(wxEVT_BUTTON,[this](wxCommandEvent&){try{RefineDialog();}catch(std::exception const& error){SetStatus(wxString::FromUTF8(error.what()));}});heading->Add(analyze,0);layout->Add(heading,0,wxEXPAND|wxLEFT|wxRIGHT|wxBOTTOM,14);
    timing_target=new wxChoice(parent,wxID_ANY);timing_target->SetName("timing-target");studio_ui::field(timing_target);layout->Add(timing_target,0,wxEXPAND|wxLEFT|wxRIGHT|wxBOTTOM,14);
    auto times=new wxFlexGridSizer(2,6,8);times->AddGrowableCol(0);times->AddGrowableCol(1);
    for(auto label:{L"开始（毫秒）",L"结束（毫秒）"})times->Add(studio_ui::label(parent,label,9,studio_ui::muted));
    timing_begin=new wxSpinCtrl(parent,wxID_ANY,"",wxDefaultPosition,wxDefaultSize,wxSP_ARROW_KEYS|wxTE_PROCESS_ENTER,0,2147480000,0);
    timing_end=new wxSpinCtrl(parent,wxID_ANY,"",wxDefaultPosition,wxDefaultSize,wxSP_ARROW_KEYS|wxTE_PROCESS_ENTER,0,2147480000,5000);
    timing_begin->SetName("timing-start");timing_end->SetName("timing-end");
    for(auto control:{timing_begin,timing_end}){control->SetMinSize(FromDIP(wxSize(0,30)));control->SetIncrement(10);times->Add(control,1,wxEXPAND);control->Bind(wxEVT_TEXT,[this](wxCommandEvent&){if(!loading){timing_dirty=true;save_button->Enable(true);dirty_label->SetLabel(L"时间有草稿 · 点应用时间或应用本行修改");}});control->Bind(wxEVT_TEXT_ENTER,[this](wxCommandEvent&){try{ApplyCalibration();}catch(std::exception const& error){SetStatus(wxString::FromUTF8(error.what()));}});}
    layout->Add(times,0,wxEXPAND|wxLEFT|wxRIGHT|wxBOTTOM,14);
    auto row=[&]{return new wxBoxSizer(wxHORIZONTAL);};
    auto add=[&](wxBoxSizer *sizer,wxString label,char const *name,std::function<void()> run,bool primary=false){auto b=new StudioButton(parent,label,primary?StudioButton::Kind::Primary:StudioButton::Kind::Secondary,wxSize(0,32));b->SetMinSize(FromDIP(wxSize(0,32)));b->SetName(name);b->Bind(wxEVT_BUTTON,[this,run](wxCommandEvent&){try{run();}catch(std::exception const& error){SetStatus(wxString::FromUTF8(error.what()));}});sizer->Add(b,1,wxRIGHT,4);return b;};
    auto actions=row();add(actions,L"应用时间","timing-apply",[this]{ApplyCalibration();},true);add(actions,L"定位 / 放大","timing-focus",[this]{FocusTiming(true);});layout->Add(actions,0,wxEXPAND|wxLEFT|wxRIGHT|wxBOTTOM,10);
    auto nudge=row();timing_step=new wxChoice(parent,wxID_ANY);for(auto label:{L"10ms",L"50ms",L"100ms"})timing_step->Append(label);timing_step->SetSelection(0);timing_step->SetMinSize(FromDIP(wxSize(70,30)));nudge->Add(timing_step,0,wxRIGHT,5);
    auto move=[this](int edge,int direction){int steps[]={10,50,100};ApplyCalibration(edge,direction*steps[std::max(0,timing_step->GetSelection())]);};
    add(nudge,L"起−","timing-start-minus",[move]{move(-1,-1);});add(nudge,L"起＋","timing-start-plus",[move]{move(-1,1);});add(nudge,L"止−","timing-end-minus",[move]{move(1,-1);});add(nudge,L"止＋","timing-end-plus",[move]{move(1,1);});layout->Add(nudge,0,wxEXPAND|wxLEFT|wxRIGHT|wxBOTTOM,10);
    auto listen=row();add(listen,L"听起点","timing-listen-start",[this]{AuditionCalibration(-1);});add(listen,L"听整段","timing-listen",[this]{AuditionCalibration(0);});add(listen,L"听终点","timing-listen-end",[this]{AuditionCalibration(1);});layout->Add(listen,0,wxEXPAND|wxLEFT|wxRIGHT|wxBOTTOM,10);
    auto navigation=row();add(navigation,L"上一词","timing-prev",[this]{if(!FlushChanges())return;timing_target->SetSelection(std::max(0,timing_target->GetSelection()-1));RefreshCalibration();FocusTiming(true);});add(navigation,L"下一词","timing-next",[this]{if(!FlushChanges())return;timing_target->SetSelection(std::min(int(timing_target->GetCount())-1,timing_target->GetSelection()+1));RefreshCalibration();FocusTiming(true);});add(navigation,L"确认 → 下一行","timing-confirm-next",[this]{ConfirmNext();},true);layout->Add(navigation,0,wxEXPAND|wxLEFT|wxRIGHT|wxBOTTOM,10);
    auto_focus=new wxCheckBox(parent,wxID_ANY,L"换行时自动定位时间轴");auto_focus->SetValue(true);layout->Add(auto_focus,0,wxLEFT|wxRIGHT|wxBOTTOM,14);
    timing_target->Bind(wxEVT_CHOICE,[this](wxCommandEvent&){int target=timing_target->GetSelection();if(!FlushChanges()){timing_target->SetSelection(timing_current+1);return;}timing_target->SetSelection(std::min(target,int(timing_target->GetCount())-1));RefreshCalibration();FocusTiming(true);});
    auto hint=studio_ui::label(parent,L"拖绿 / 蓝两端调整整行，拖中间线调整音节。Ctrl+Enter 确认下一行；F6 定位。时间以 ASS 的 10ms 精度保存。",8.5,studio_ui::muted);wrap(hint,hint->GetLabel(),FromDIP(350));layout->Add(hint,0,wxEXPAND|wxLEFT|wxRIGHT|wxBOTTOM,14);
}

void StudioPanel::RefreshCalibration(bool reset){
    if(!timing_target||timing_dirty)return;
    auto line=context->selectionController->GetActiveLine();int selection=reset?0:std::max(0,timing_target->GetSelection());
    bool prior=loading;loading=true;timing_target->Clear();timing_target->Append(L"整行起止");
    if(line){auto data=ReadLine(line);auto const& value=object(data);auto const& list=static_cast<json::Array const&>(value.at("units"));
        if(pause_button){pause_button->Enable(!text(value,"text").empty());try{auto count=studio_pauses::gaps(data).size();pause_button->SetLabel(wxString::Format(L"停顿 · %zu处",count));}catch(std::exception const&){pause_button->SetLabel(L"停顿检查");}pause_button->SetToolTip(L"列出未分配给歌词的时间，可保留或并入前／后一音节；可试听和撤销。");}
        for(size_t i=0;i<list.size();++i){auto const& unit=object(list[i]);timing_target->Append(wxString::Format(L"词 %zu · ",i+1)+wxString::FromUTF8(text(unit,"text"))+L"  "+wxString::FromUTF8(text(unit,"kana")));}
        selection=std::min(selection,int(list.size()));timing_target->SetSelection(selection);timing_current=selection-1;
        auto const& selected=selection?object(list[selection-1]):value;timing_begin->SetValue(ms(selected,"start"));timing_end->SetValue(ms(selected,"end"));
        if(reading_evidence){auto found=value.find("reading_review");wxString label=L"转录辅助复核会显示原读音、建议和依据；人工注音受保护。";
            if(found!=value.end()){auto const& proof=object(found->second);label=L"最近依据："+wxString::FromUTF8(text(proof,"recognized"));if(label.size()>100)label=label.Left(100)+L"…";if(auto stale=proof.find("stale");stale!=proof.end()&&static_cast<json::Boolean const&>(stale->second))label=L"时间或原文已变化，请重新分析读音依据。";}
            wrap(reading_evidence,label,FromDIP(350));}
    }else{timing_target->SetSelection(0);timing_current=-1;}
    timing_target->Enable(line!=nullptr);timing_begin->Enable(line!=nullptr);timing_end->Enable(line!=nullptr);loading=prior;
}

void StudioPanel::ApplyCalibration(int edge,int amount){
    int begin=timing_begin->GetValue(),end=timing_end->GetValue(),target=timing_current;
    auto line=context->selectionController->GetActiveLine();if(!line||line->Id!=active_id)throw std::runtime_error("编辑目标已变化，请保存或放弃原草稿");
    if(fields_dirty){SaveFields();fields_snapshot=studio_workflow::encode(ReadLine(line));}
    auto before=ReadLine(line);
    if(!fields_snapshot.empty()&&studio_workflow::encode(before)!=fields_snapshot && !fields_dirty)throw std::runtime_error("工程已变化，请重新读取后再调整时间");
    if(edge<0)begin+=amount;if(edge>0)end+=amount;
    auto value=studio_calibration::timed(before,target,begin,end);WriteLine(line,value,true);timing_dirty=false;
    context->ass->Commit(L"人工校准起止时间",AssFile::COMMIT_DIAG_FULL|AssFile::COMMIT_EXTRADATA);RefreshLine();
    timing_target->SetSelection(std::min(target+1,int(timing_target->GetCount())-1));RefreshCalibration();
    SetStatus(L"时间已应用，可撤销。相接边界同步衔接，内部人工音节尽量保持；被压缩的估算时间请试听。");
}

void StudioPanel::FocusTiming(bool word){
    if(!context->project->AudioProvider())return;auto line=context->selectionController->GetActiveLine();if(!line)return;
    if(!context->frame->IsAudioShown())context->frame->SetDisplayMode(-1,1);
    int begin=word&&timing_begin?timing_begin->GetValue():int(line->Start),end=word&&timing_end?timing_end->GetValue():int(line->End);
    if(end<=begin)return;auto display=context->audioBox->StudioDisplay();int width=std::max(100,display->GetClientSize().x);int duration=end-begin+600;
    for(int n=0;n<80;++n){int visible=display->TimeFromRelativeX(width)-display->TimeFromRelativeX(0),zoom=display->GetZoomLevel();if(visible<duration&&zoom>-30)display->SetZoomLevel(zoom-1);else if(visible>duration*1.35&&zoom<50)display->SetZoomLevel(zoom+1);else break;}
    display->ScrollTimeRangeInView(TimeRange(std::max(0,begin-300),end+300));
    if(word&&context->karaoke->IsEnabled())context->audioController->GetTimingController()->OnLeftClick(begin+(end-begin)/2,false,false,0,0);
}

void StudioPanel::AuditionCalibration(int edge){
    auto provider=context->project->AudioProvider();if(!provider)throw std::runtime_error("请先添加音视频");
    int begin=timing_begin->GetValue(),end=timing_end->GetValue();if(end<=begin)throw std::runtime_error("结束须晚于开始");
    int duration=int(provider->GetNumSamples()*1000/provider->GetSampleRate());
    int first=edge<0?begin-350:edge>0?end-700:begin-150,last=edge<0?begin+700:edge>0?end+350:end+150;
    first=std::clamp(first,0,duration);last=std::clamp(last,0,duration);if(last<=first)throw std::runtime_error("该时间已超出媒体长度");
    loop_timer.Stop();loop->SetValue(false);context->audioController->PlayRange(TimeRange(first,last));
}

void StudioPanel::StopAudition(){loop_timer.Stop();if(loop)loop->SetValue(false);context->audioController->Stop();context->videoController->Stop();}

void StudioPanel::ConfirmNext(){
    if(!FlushChanges())return;auto line=context->selectionController->GetActiveLine();if(!line)return;
    int before=line->Id;auto value=studio_calibration::confirmed(ReadLine(line));WriteLine(line,value,true);context->ass->Commit(L"人工确认本行时间",AssFile::COMMIT_DIAG_FULL|AssFile::COMMIT_EXTRADATA);RefreshLine();Navigate(1,true);FocusTiming();SetStatus(context->selectionController->GetActiveLine()->Id==before?L"本行已确认；没有其他待校准行。可撤销。":L"本行时间已确认；已定位下一待校准行。可撤销。");
}

json::UnknownElement StudioPanel::RecentTranscript(){
    transcript_verified=false;
    auto media=context->project->VideoName();if(media.empty())media=context->project->AudioName();if(media.empty())return json::Array();
    auto home=test_worker_home.empty()?std::filesystem::path(wxStandardPaths::Get().GetUserDataDir().ToStdWstring()):test_worker_home;
    std::vector<std::filesystem::path> folders;std::error_code error;
    for(auto const& entry:std::filesystem::directory_iterator(home/"tasks",error))if(entry.is_directory())folders.push_back(entry.path());
    std::sort(folders.rbegin(),folders.rend());
    for(auto const& folder:folders)try{auto task=file_json(folder/"task.json");auto const& meta=object(task);auto kind=text(meta,"action");if(kind!="transcribe"&&kind!="transcribe_match")continue;
        auto source=text(meta,"media");if(source.empty()||normalized_path(std::filesystem::u8path(source))!=normalized_path(media))continue;
        bool verified=false;auto size=text(meta,"media_size"),stamp=text(meta,"media_stamp");
        if(!size.empty()&&!stamp.empty()){
            std::error_code ec;auto current_size=std::filesystem::file_size(media,ec);if(ec||size!=std::to_string(current_size))continue;
            auto current_stamp=std::filesystem::last_write_time(media,ec);if(ec||stamp!=std::to_string(current_stamp.time_since_epoch().count()))continue;verified=true;
        }
        auto result=file_json(folder/"result.json");auto const& data=object(result);auto found=data.find("transcript");if(found==data.end()&&kind=="transcribe")found=data.find("suggestions");if(found!=data.end()){transcript_verified=verified;return studio_workflow::copy(found->second);}
    }catch(std::exception const&){}return json::Array();
}

void StudioPanel::RunRefinement(bool use_llm,int gap,std::filesystem::path const& source,bool preserve_legacy,bool preserve_manual){
    if(pid)throw std::runtime_error("请先等待当前任务完成");if(!FlushChanges())return;
    auto lines=ReadLines(!segment_scope||segment_scope->GetSelection()==0);if(lines.empty())throw std::runtime_error("先选择要校对的原歌词");
    auto transcript=RecentTranscript();if(!source.empty()){auto loaded=file_json(source);auto const& data=object(loaded);auto found=data.find("transcript");if(found==data.end())found=data.find("suggestions");if(found==data.end())found=data.find("lines");if(found==data.end())throw std::runtime_error("JSON 中没有转录行");transcript=studio_workflow::copy(found->second);}
    for(auto const& row:static_cast<json::Array const&>(transcript))studio_document::karaoke(row);
    json::Object request;request["action"]="refine";request["provider"]=use_llm?"deepseek":"local";request["use_llm"]=use_llm;request["gap_ms"]=gap;request["transcript_verified"]=transcript_verified;request["manual_source"]=!source.empty();request["transcript"]=std::move(transcript);request["context"]=ReadLines(false);
    request["preserve_legacy"]=preserve_legacy;request["preserve_manual"]=preserve_manual;
    auto media=context->project->VideoName();if(media.empty())media=context->project->AudioName();request["media"]=std::string(wxString(media.wstring()).utf8_str());
    snapshots.clear();for(auto const& row:lines)snapshots[std::stoi(text(object(row),"id"))]=studio_workflow::encode(row);request["lines"]=std::move(lines);Launch(std::move(request));
}

void StudioPanel::RefineDialog(bool use_llm,std::function<int(wxDialog&)> const& inspect){
    wxDialog dialog(this,wxID_ANY,L"转录辅助二次校对",wxDefaultPosition,FromDIP(wxSize(600,580)),wxDEFAULT_DIALOG_STYLE|wxRESIZE_BORDER);dialog.SetMinSize(FromDIP(wxSize(600,560)));dialog.SetFont(studio_ui::font());dialog.SetBackgroundColour(studio_ui::paper);auto layout=new wxBoxSizer(wxVERTICAL);
    auto available=RecentTranscript();auto found=!static_cast<json::Array const&>(available).empty();auto source_label=studio_ui::label(&dialog,found?L"已找到当前媒体的转录，将结合上下句和词典复核。":L"未找到当前媒体转录。可浏览结果 JSON；没有转录时只提供词典和上下文建议。",10,studio_ui::ink);source_label->Wrap(FromDIP(540));layout->Add(source_label,0,wxEXPAND|wxALL,16);
    wrap(source_label,source_label->GetLabel(),FromDIP(540));source_label->SetName("refine-source");auto scope=new wxChoice(&dialog,wxID_ANY);scope->SetName("refine-scope");scope->Append(L"处理左侧选中行");scope->Append(L"处理全部未保护歌词");scope->SetSelection(segment_scope->GetSelection());layout->Add(scope,0,wxEXPAND|wxLEFT|wxRIGHT|wxBOTTOM,16);
    if(found&&!transcript_verified)wrap(source_label,L"找到当前路径的旧转录，但旧版未记录文件版本。若媒体曾被替换，请先选正确的转录 JSON。",FromDIP(540));
    auto cloud=new wxCheckBox(&dialog,wxID_ANY,L"使用 DeepSeek 复核特殊唱法及译文（联网）");cloud->SetName("refine-mode");cloud->SetValue(use_llm);layout->Add(cloud,0,wxLEFT|wxRIGHT|wxBOTTOM,16);
    auto manual=new wxCheckBox(&dialog,wxID_ANY,L"保留明确手工修改的注音（取消后可重新复核）");manual->SetName("refine-preserve-manual");manual->SetValue(true);layout->Add(manual,0,wxLEFT|wxRIGHT|wxBOTTOM,8);
    auto legacy=new wxCheckBox(&dialog,wxID_ANY,L"保留旧版来源不明的读音");legacy->SetName("refine-preserve-legacy");layout->Add(legacy,0,wxLEFT|wxRIGHT|wxBOTTOM,16);
    auto gap=new wxSpinCtrl(&dialog,wxID_ANY,"",wxDefaultPosition,wxDefaultSize,wxSP_ARROW_KEYS,0,500,120);gap->SetName("refine-gap");layout->Add(studio_ui::label(&dialog,L"收拢未人工校准的短空隙（ms，0 为不处理）",9,studio_ui::muted),0,wxLEFT|wxRIGHT,16);layout->Add(gap,0,wxEXPAND|wxALL,16);
    auto note=studio_ui::label(&dialog,L"人工确认的时间保持，读音仍可复核。锁定行跳过；超过阈值的停顿保留。原歌词不变，全部建议先试听审核。\nDeepSeek 按账户计费，只发送歌词和转录上下文；离线模式不联网。",9,studio_ui::muted);wrap(note,note->GetLabel(),FromDIP(540));layout->Add(note,0,wxEXPAND|wxLEFT|wxRIGHT|wxBOTTOM,16);
    std::filesystem::path source;auto browse=new wxButton(&dialog,wxID_ANY,L"浏览已有转录 JSON…");browse->Bind(wxEVT_BUTTON,[&](wxCommandEvent&){wxFileDialog picker(&dialog,L"已有转录","","",L"JSON (*.json)|*.json",wxFD_OPEN|wxFD_FILE_MUST_EXIST);if(picker.ShowModal()==wxID_OK){source=std::filesystem::path(picker.GetPath().ToStdWstring());source_label->SetLabel(L"使用："+picker.GetFilename());}});layout->Add(browse,0,wxLEFT|wxRIGHT|wxBOTTOM,16);layout->AddStretchSpacer();layout->Add(dialog.CreateButtonSizer(wxOK|wxCANCEL),0,wxEXPAND|wxALL,16);dialog.SetSizer(layout);
    if((inspect?inspect(dialog):dialog.ShowModal())==wxID_OK){segment_scope->SetSelection(scope->GetSelection());RunRefinement(cloud->GetValue(),gap->GetValue(),source,legacy->GetValue(),manual->GetValue());}
}
