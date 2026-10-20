// Copyright (c) 2026 Shengao Karaoke Studio contributors. MIT.
// This adapter uses Aegisub's licensed timing, project and undo APIs.
#include "studio_panel.h"
#include "studio_karaoke.h"
#include "frame_main.h"
#include "studio_document.h"
#include "studio_workflow.h"
#include "studio_editing.h"
#include "ass_dialogue.h"
#include "ass_file.h"
#include "ass_karaoke.h"
#include "async_video_provider.h"
#include "audio_controller.h"
#include "audio_karaoke.h"
#include "compat.h"
#include "include/aegisub/context.h"
#include "project.h"
#include "selection_controller.h"
#include "subs_controller.h"
#include "subtitle_format_ass.h"
#include "video_controller.h"
#include "time_range.h"

#include <libaegisub/ass/karaoke.h>
#include <libaegisub/json.h>

#include <wx/button.h>
#include <wx/checkbox.h>
#include <wx/checklst.h>
#include <wx/choice.h>
#include <wx/dialog.h>
#include <wx/filedlg.h>
#include <wx/filename.h>
#include <wx/grid.h>
#include <wx/msgdlg.h>
#include <wx/process.h>
#include <wx/sizer.h>
#include <wx/statline.h>
#include <wx/stattext.h>
#include <wx/stdpaths.h>
#include <wx/textctrl.h>
#include <wx/textdlg.h>
#include <wx/tokenzr.h>
#include <wx/utils.h>
#include <wx/wfstream.h>

#include <algorithm>
#include <fstream>
#include <memory>
#include <sstream>
#include <vector>

namespace {
std::string utf8(wxString const& s) { return std::string(s.utf8_str()); }
wxString display(std::string const& s) { return wxString::FromUTF8(s); }
std::string string(json::UnknownElement const& v) { return static_cast<json::String const&>(v); }
int number(json::UnknownElement const& v) { return static_cast<int>(static_cast<json::Integer const&>(v)); }
bool json_bool(json::Object const& o, std::string const& key, bool fallback=false) {
    auto it=o.find(key); return it==o.end()?fallback:static_cast<json::Boolean const&>(it->second);
}
std::string field(json::Object const& o, std::string const& key, std::string fallback="") {
    auto it=o.find(key); return it==o.end()?fallback:string(it->second);
}
std::string encode(json::UnknownElement const& v) { std::ostringstream s;agi::JsonWriter::Write(v,s);return s.str(); }
json::UnknownElement decode(std::string const& s) { std::istringstream stream(s);return agi::json_util::parse(stream); }
json::UnknownElement read_json(std::filesystem::path const& p) { std::ifstream stream(p,std::ios::binary);return agi::json_util::parse(stream); }
std::string single_line_json(json::UnknownElement const& v) {
    auto text=encode(v);
    text.erase(std::remove(text.begin(),text.end(),'\n'),text.end());
    text.erase(std::remove(text.begin(),text.end(),'\r'),text.end());
    return text;
}
std::string literal(std::string text) {
    for (auto& c:text) if(c=='{'||c=='}'||c=='\\'||c=='\r'||c=='\n') c=' ';
    return text;
}
json::Object metadata(AssFile *file, AssDialogue *line) {
    for(auto const& entry:file->GetExtradata(line->ExtradataIds)) {
        if(entry.key=="shengao/annotation") {
            try { auto value=decode(entry.value); auto& object=static_cast<json::Object&>(value); return std::move(object); } catch(...) { }
        }
    }
    return {};
}
void store_metadata(AssFile *file, AssDialogue *line, json::Object value) {
    auto ids=line->ExtradataIds.get();
    for(auto const& entry:file->GetExtradata(ids)) if(entry.key=="shengao/annotation")
        ids.erase(std::remove(ids.begin(),ids.end(),entry.id),ids.end());
    ids.push_back(file->AddExtradata("shengao/annotation",encode(json::UnknownElement(std::move(value)))));
    line->ExtradataIds=ids;
}
AssDialogue *find_line(agi::Context *c,int id) {
    for(auto& line:c->ass->Events) if(line.Id==id) return &line;
    return nullptr;
}
}

StudioPanel::StudioPanel(wxWindow *parent,agi::Context *c)
:StudioSurface(parent,wxID_ANY,wxSize(430,-1)),context(c),timer(this),loop_timer(this) {
    BuildWorkspace();
    Bind(wxEVT_TIMER,&StudioPanel::Poll,this,timer.GetId());
    Bind(wxEVT_TIMER,[this](wxTimerEvent&){if(loop->GetValue()&&context->project->AudioProvider()&&!context->audioController->IsPlaying())context->audioController->PlayPrimaryRange();},loop_timer.GetId());
    Bind(wxEVT_END_PROCESS,&StudioPanel::EndProcess,this);
    BindConnection(c->selectionController->AddActiveLineListener([this](AssDialogue*) { RefreshLine(); }));
    BindConnection(c->ass->AddCommitListener([this](int,AssDialogue const*) { if(preview_active){preview_stale=true;preview_active=false;}if(!fields_dirty)RefreshLine();else UpdateOverview(); }));
    BindConnection(c->project->AddAudioProviderListener([this](agi::AudioProvider* provider){if(!provider){loop_timer.Stop();loop->SetValue(false);}UpdateOverview();}));
    BindConnection(c->project->AddVideoProviderListener([this](AsyncVideoProvider*){UpdateOverview();}));
    c->frame->Bind(wxEVT_CHAR_HOOK,[this](wxKeyEvent& event){try{
        if(auto focus=wxWindow::FindFocus();focus&&wxGetTopLevelParent(focus)!=context->frame){event.Skip();return;}
        if(event.GetKeyCode()==WXK_F6){FocusTiming(true);return;}
        if(event.ControlDown()&&(event.GetKeyCode()==WXK_RETURN||event.GetKeyCode()==WXK_NUMPAD_ENTER)){ConfirmNext();return;}
        if(event.GetKeyCode()==WXK_ESCAPE&&context->audioController->IsPlaying()){StopAudition();return;}
    }catch(std::exception const& error){SetStatus(display(error.what()));}event.Skip();});
    RefreshLine();
}

StudioPanel::~StudioPanel() {
    timer.Stop();
    loop_timer.Stop();
    if(pid) {Cancel();if(process)process->Detach();}
}

bool StudioPanel::PrepareClose(std::function<int(bool)> const& decision) {
    if(fields_dirty||timing_dirty){
        auto answer=decision?decision(false):wxMessageBox(L"当前注音／音节编辑尚未保存。保存到工程？",L"未保存的编辑",wxYES_NO|wxCANCEL|wxICON_QUESTION,this);
        if(answer==wxCANCEL)return false;
        if(answer==wxYES){if(!FlushChanges())return false;}
        else {fields_dirty=false;timing_dirty=false;}
    }
    if(pid&&(decision?decision(true):wxMessageBox(L"后台任务仍在运行。关闭软件会请求取消本地任务；云端可能已经计费。关闭？",L"后台任务",wxYES_NO|wxICON_QUESTION,this))!=wxYES)return false;
    return true;
}

bool StudioPanel::FlushChanges() {
    if(!fields_dirty&&!timing_dirty)return true;
    try{if(timing_dirty)ApplyCalibration();else SaveFields();return true;}
    catch(std::exception const& e){wxMessageBox(display(e.what()),L"无法保存注音编辑",wxOK|wxICON_ERROR,this);return false;}
}

void StudioPanel::DiscardFields() {
    if(fields_dirty&&wxMessageBox(L"放弃侧栏中尚未保存的注音和音节编辑？",L"重新读取当前行",wxYES_NO|wxICON_QUESTION,this)!=wxYES)return;
    fields_dirty=false;timing_dirty=false;RefreshLine();
}

json::UnknownElement StudioPanel::ReadLine(AssDialogue *line) {
    auto meta=metadata(context->ass.get(),line);
    json::Object result;
    result["id"]=std::to_string(line->Id);result["start"]=int(line->Start);result["end"]=int(line->End);
    result["kana"]=field(meta,"kana");result["romaji"]=field(meta,"romaji");result["translation"]=field(meta,"translation");
    result["locked"]=json_bool(meta,"locked");result["reviewed"]=json_bool(meta,"reviewed");
    if(auto found=meta.find("reading_review");found!=meta.end())result["reading_review"]=studio_workflow::copy(found->second);
    json::Array array;std::string text;
    auto parsed=ParseKaraokeSyllables(line);
    json::Array const *old=nullptr;
    auto old_it=meta.find("units");if(old_it!=meta.end())old=&static_cast<json::Array const&>(old_it->second);
    int index=0;
    for(auto const& syl:parsed) {
        if(syl.text.empty())continue;
        std::string fragment=studio_document::plain(syl.text),reading;
        auto pipe=fragment.find('|');if(pipe!=std::string::npos){reading=fragment.substr(pipe+1);fragment=fragment.substr(0,pipe);if(reading.starts_with('!'))reading.erase(0,1);}
        if((fragment=="#"||fragment=="＃")&&!array.empty()){
            auto& previous=static_cast<json::Object&>(array.back());
            auto found=previous.find("highlights");
            if(found==previous.end()){
                json::Array highlights;json::Object first;first["kana"]=field(previous,"kana");
                first["start"]=number(previous.at("start"));first["end"]=number(previous.at("end"));first["source"]="manual";
                highlights.emplace_back(std::move(first));previous["highlights"]=std::move(highlights);
            }
            auto& highlights=static_cast<json::Array&>(previous.at("highlights"));json::Object next;
            next["kana"]=reading;next["start"]=syl.start_time;next["end"]=std::min(int(line->End),syl.start_time+syl.duration);next["source"]="manual";
            highlights.emplace_back(std::move(next));previous["kana"]=field(previous,"kana")+reading;
            previous["end"]=std::min(int(line->End),syl.start_time+syl.duration);continue;
        }
        json::Object unit;
        unit["text"]=fragment;unit["start"]=std::max(int(line->Start),syl.start_time);
        unit["end"]=std::min(int(line->End),std::max(syl.start_time,syl.start_time+syl.duration));
        unit["kana"]=reading;unit["romaji"]="";unit["source"]="imported";unit["locked"]=false;
        if(old&&index<int(old->size())) {
            auto const& previous=static_cast<json::Object const&>((*old)[index]);
            if(field(previous,"text")==fragment){
                unit["kana"]=reading.empty()?field(previous,"kana"):reading;unit["romaji"]=field(previous,"romaji");
                unit["locked"]=json_bool(previous,"locked");
            }
        }
        text+=fragment;array.emplace_back(std::move(unit));++index;
    }
    if(parsed.size()==1&&parsed[0].duration==0)array.clear();
    bool timing_changed=false;
    if(meta.find("start")!=meta.end())timing_changed=(number(meta.at("start"))+5)/10!=(int(line->Start)+5)/10 ||
        (number(meta.at("end"))+5)/10!=(int(line->End)+5)/10 || field(meta,"text")!=text;
    for(size_t i=0;i<array.size();++i){
        auto& unit=static_cast<json::Object&>(array[i]);
        if(!old||i>=old->size()){timing_changed=true;continue;}
        auto const& previous=static_cast<json::Object const&>((*old)[i]);
        unit["reading_source"]=field(previous,"text")==field(unit,"text")&&field(previous,"kana")==field(unit,"kana")?field(previous,"reading_source"):"manual";
        bool same=field(previous,"text")==field(unit,"text") &&
            (number(previous.at("start"))+5)/10==(number(unit.at("start"))+5)/10 &&
            (number(previous.at("end"))+5)/10==(number(unit.at("end"))+5)/10;
        unit["source"]=same?field(previous,"source","imported"):"manual";
        if(!same)timing_changed=true;
        auto parts=unit.find("highlights");auto old_parts=previous.find("highlights");
        if(parts!=unit.end()&&old_parts!=previous.end()){
            auto& current=static_cast<json::Array&>(parts->second);auto const& prior=static_cast<json::Array const&>(old_parts->second);
            for(size_t j=0;j<current.size();++j){auto& part=static_cast<json::Object&>(current[j]);
                if(j>=prior.size()){timing_changed=true;continue;}
                auto const& before=static_cast<json::Object const&>(prior[j]);
                bool equal=field(part,"kana")==field(before,"kana") &&
                    (number(part.at("start"))+5)/10==(number(before.at("start"))+5)/10 &&
                    (number(part.at("end"))+5)/10==(number(before.at("end"))+5)/10;
                part["source"]=equal?field(before,"source","imported"):"manual";
                if(!equal)timing_changed=true;
            }
        }
    }
    if(timing_changed)result["reviewed"]=false;
    if(timing_changed&&result.find("reading_review")!=result.end())static_cast<json::Object&>(result["reading_review"])["stale"]=true;
    auto match=meta.find("match");
    if(match!=meta.end()){
        result["match"]=studio_workflow::copy(match->second);
        if(timing_changed){auto& info=static_cast<json::Object&>(result["match"]);info["status"]="manual";info["reason"]="时间或原文已人工修改，原匹配分数仅供参考";}
    }
    result["text"]=text;result["units"]=std::move(array);
    return json::UnknownElement(std::move(result));
}

json::Array StudioPanel::ReadLines(bool selected) {
    json::Array result;
    auto selection=context->selectionController->GetSelectedSet();
    for(auto& line:context->ass->Events) {
        if(line.Comment || (selected&&!selection.count(&line)))continue;
        auto data=ReadLine(&line);auto const& object=static_cast<json::Object const&>(data);
        if(field(object,"text").empty())continue;
        result.emplace_back(std::move(data));
    }
    return result;
}

void StudioPanel::RefreshLine() {
    auto line=context->selectionController->GetActiveLine();
    bool line_changed=(line?line->Id:-1)!=active_id;
    if(fields_dirty||timing_dirty) {
        // Retain unsaved values in the panel until explicitly saved or discarded.
        SetStatus(L"注音尚未保存：先保存当前编辑，再切换编辑目标。");return;
    }
    loading=true;active_id=line?line->Id:-1;
    if(units->GetNumberRows())units->DeleteRows(0,units->GetNumberRows());
    if(line) {
        auto value=ReadLine(line);auto const& object=static_cast<json::Object const&>(value);
        fields_snapshot=encode(value);
        kana->ChangeValue(display(field(object,"kana")));romaji->ChangeValue(display(field(object,"romaji")));translation->ChangeValue(display(field(object,"translation")));
        locked->SetValue(json_bool(object,"locked"));reviewed->SetValue(json_bool(object,"reviewed"));
        auto const& list=static_cast<json::Array const&>(object.at("units"));
        if(!list.empty())units->AppendRows(list.size());
        for(int row=0;row<int(list.size());++row){auto const& unit=static_cast<json::Object const&>(list[row]);
            auto reading=field(unit,"kana");auto highlights=unit.find("highlights");
            if(highlights!=unit.end()){reading.clear();for(auto const& part:static_cast<json::Array const&>(highlights->second)){if(!reading.empty())reading+='|';reading+=field(static_cast<json::Object const&>(part),"kana");}}
            units->SetCellValue(row,0,display(field(unit,"text")));units->SetCellValue(row,1,display(reading));units->SetCellValue(row,2,display(field(unit,"romaji")));
            units->SetReadOnly(row,0);
            units->SetCellValue(row,3,wxString::Format("%d",number(unit.at("start"))));units->SetCellValue(row,4,wxString::Format("%d",number(unit.at("end"))));
            auto source=field(unit,"source");
            auto source_label=source=="estimated"?L"估算":source=="manual"?L"手动":source=="alignment"?L"对齐":source=="recognition"?L"识别":source=="word"?L"词级":source=="matched"?L"匹配":source=="mapped"?L"映射":L"导入";
            units->SetCellValue(row,5,source_label);units->SetReadOnly(row,5);
            if(field(unit,"source")=="estimated")for(int col=0;col<6;++col)units->SetCellBackgroundColour(row,col,wxColour(255,246,220));}
    }else{fields_snapshot.clear();kana->Clear();romaji->Clear();translation->Clear();locked->SetValue(false);reviewed->SetValue(false);}
    loading=false;fields_dirty=false;RefreshCalibration(line_changed);UpdateOverview();
    if(line_changed&&auto_focus&&auto_focus->GetValue())FocusTiming();
}

void StudioPanel::WriteLine(AssDialogue *line,json::UnknownElement const& value,bool update_times) {
    auto const& object=static_cast<json::Object const&>(value);
    int start=number(object.at("start")),end=number(object.at("end"));
    auto text=studio_document::karaoke(value);
    // Editing metadata must not destroy manually styled ASS override tags.
    if(!std::string(line->Text).empty()){
        try{if(studio_workflow::shape(ReadLine(line))==studio_workflow::shape(value))text=std::string(line->Text);
            else{AssDialogue changed;changed.Start=start;changed.End=end;changed.Text=text;auto parsed=ParseKaraokeSyllables(&changed);studio_karaoke::preserve_tags(ParseKaraokeSyllables(line),parsed);std::string updated;bool timed=!static_cast<json::Array const&>(object.at("units")).empty();for(auto const& syllable:parsed)updated+=syllable.GetText(timed);text=std::move(updated);}
        }catch(std::exception const&){}
    }
    if(update_times){line->Start=start;line->End=end;}
    line->Text=text;
    auto copy=decode(encode(value));auto& meta=static_cast<json::Object&>(copy);store_metadata(context->ass.get(),line,std::move(meta));
}

void StudioPanel::SaveFields() {
    units->SaveEditControlValue();
    auto line=find_line(context,active_id);if(!line)throw std::runtime_error("当前歌词已被删除，请重新选择");
    auto data=ReadLine(line);auto& object=static_cast<json::Object&>(data);
    auto original_shape=studio_workflow::shape(data);
    if(encode(data)!=fields_snapshot)throw std::runtime_error("该行已在其他编辑区发生修改。请先放弃侧栏未保存编辑并重新读取，再继续编辑。");
    object["kana"]=utf8(kana->GetValue());object["romaji"]=utf8(romaji->GetValue());object["translation"]=utf8(translation->GetValue());
    object["locked"]=locked->GetValue();object["reviewed"]=reviewed->GetValue();
    auto const& old_units=static_cast<json::Array const&>(object.at("units"));
    json::Array array;std::string combined;
    for(int row=0;row<units->GetNumberRows();++row){long start=0,end=0;
        if(!units->GetCellValue(row,3).ToLong(&start)||!units->GetCellValue(row,4).ToLong(&end))throw std::runtime_error("请填写整数毫秒时间");
        json::Object unit;unit["text"]=utf8(units->GetCellValue(row,0));unit["romaji"]=utf8(units->GetCellValue(row,2));
        auto kana_value=units->GetCellValue(row,1);std::string joined_kana;
        if(kana_value.Contains('|')){
            wxArrayString parts=wxSplit(kana_value,'|');json::Array highlights;
            for(size_t i=0;i<parts.size();++i){if(parts[i].empty())throw std::runtime_error("拆分音节不能留空");
                json::Object part;part["kana"]=utf8(parts[i]);part["start"]=int(start+(end-start)*i/parts.size());part["end"]=int(start+(end-start)*(i+1)/parts.size());part["source"]="estimated";
                joined_kana+=utf8(parts[i]);highlights.emplace_back(std::move(part));}
            unit["highlights"]=std::move(highlights);
        }else joined_kana=utf8(kana_value);
        unit["kana"]=joined_kana;
        unit["reading_source"]="manual";
        std::string source="manual";bool unit_locked=false;
        if(row<int(old_units.size())){auto const& old=static_cast<json::Object const&>(old_units[row]);
            if(field(old,"kana")==joined_kana&&field(old,"romaji")==field(unit,"romaji"))unit["reading_source"]=field(old,"reading_source");
            unit_locked=json_bool(old,"locked");
            if(number(old.at("start"))==start&&number(old.at("end"))==end&&field(old,"text")==field(unit,"text")){
                source=field(old,"source","imported");
                if(kana_value.Contains('|')){
                    auto previous=old.find("highlights");
                    bool same_parts=false;
                    if(previous!=old.end()){
                        auto const& prior=static_cast<json::Array const&>(previous->second);
                        auto const& current=static_cast<json::Array const&>(unit.at("highlights"));
                        same_parts=prior.size()==current.size();
                        for(size_t i=0;same_parts&&i<prior.size();++i)same_parts=field(static_cast<json::Object const&>(prior[i]),"kana")==field(static_cast<json::Object const&>(current[i]),"kana");
                    }
                    if(same_parts)unit["highlights"]=decode(encode(previous->second));else source="estimated";
                }
            }}
        unit["start"]=int(start);unit["end"]=int(end);unit["source"]=source;unit["locked"]=unit_locked;
        combined+=field(unit,"text");array.emplace_back(std::move(unit));}
    if(!array.empty()){
        object["text"]=combined;std::string all_kana,all_romaji;
        for(auto const& value:array){auto const& word=static_cast<json::Object const&>(value);all_kana+=field(word,"kana");auto latin=field(word,"romaji");if(!latin.empty()){if(!all_romaji.empty())all_romaji+=' ';all_romaji+=latin;}}
        auto previous=decode(fields_snapshot);auto const& before=static_cast<json::Object const&>(previous);
        if(utf8(kana->GetValue())==field(before,"kana"))object["kana"]=all_kana;
        if(utf8(romaji->GetValue())==field(before,"romaji"))object["romaji"]=all_romaji;
    }
    object["units"]=std::move(array);
    if(studio_workflow::shape(data)!=original_shape){object["reviewed"]=false;auto match=object.find("match");if(match!=object.end())static_cast<json::Object&>(match->second)["status"]="manual";}
    WriteLine(line,data,false);fields_dirty=false;
    context->ass->Commit(L"保存注音和音节",AssFile::COMMIT_DIAG_FULL|AssFile::COMMIT_EXTRADATA);
    RefreshLine();SetStatus(L"本行修改已应用，可撤销。按 Ctrl+S 将工程保存到文件。");
}

void StudioPanel::ImportLyrics() {
    if(!FlushChanges())return;
    wxDialog dialog(this,wxID_ANY,L"粘贴原歌词",wxDefaultPosition,FromDIP(wxSize(670,540)),wxDEFAULT_DIALOG_STYLE|wxRESIZE_BORDER);auto layout=new wxBoxSizer(wxVERTICAL);
    auto note=new wxStaticText(&dialog,wxID_ANY,L"每行一句，保留原文空格和标点，空白行忽略。识别结果已有多余空格时，可用原歌词替换初稿，再复用转录匹配；不会重新上传。替换会重建粗轴，可撤销，媒体保持打开。");note->Wrap(600);layout->Add(note,0,wxEXPAND|wxALL,16);
    auto mode=new wxChoice(&dialog,wxID_ANY);mode->Append(L"替换现有歌词（重建粗轴，保留媒体）");mode->Append(L"追加到现有歌词末尾");bool protected_work=false;for(auto& line:context->ass->Events){auto data=ReadLine(&line);auto const& row=static_cast<json::Object const&>(data);protected_work|=json_bool(row,"locked")||json_bool(row,"reviewed");for(auto const& item:static_cast<json::Array const&>(row.at("units"))){auto const& unit=static_cast<json::Object const&>(item);protected_work|=json_bool(unit,"locked")||field(unit,"source")=="manual";}}mode->SetSelection(protected_work?1:0);layout->Add(mode,0,wxEXPAND|wxLEFT|wxRIGHT|wxBOTTOM,16);
    auto lyrics=new wxTextCtrl(&dialog,wxID_ANY,"",wxDefaultPosition,wxDefaultSize,wxTE_MULTILINE);layout->Add(lyrics,1,wxEXPAND|wxLEFT|wxRIGHT,16);layout->Add(dialog.CreateButtonSizer(wxOK|wxCANCEL),0,wxEXPAND|wxALL,16);dialog.SetSizer(layout);
    while(dialog.ShowModal()==wxID_OK){try{ImportLyricsText(lyrics->GetValue(),mode->GetSelection()==0);return;}catch(std::exception const& error){wxMessageBox(display(error.what()),L"无法导入歌词",wxOK|wxICON_INFORMATION,&dialog);}}
}

void StudioPanel::ImportLyricsText(wxString const& contents,bool replace) {
    std::vector<std::unique_ptr<AssDialogue>> prepared;int64_t start=0;
    if(!replace)for(auto const& line:context->ass->Events)if(!line.Comment&&!line.GetStrippedText().empty())start=std::max(start,int64_t(int(line.End)));
    for(auto text:wxSplit(contents,'\n')){if(text.EndsWith("\r"))text.RemoveLast();auto trimmed=text;trimmed.Trim().Trim(false);if(trimmed.empty())continue;
        if(prepared.size()>=3000||start+5000>2147480000)throw std::runtime_error("歌词过长，请分段导入（最多 3000 行）");
        auto line=std::make_unique<AssDialogue>();line->Start=int(start);line->End=int(start+5000);line->Text=studio_document::literal(utf8(text));prepared.emplace_back(std::move(line));start+=5000;
    }
    if(prepared.empty())throw std::runtime_error("请粘贴至少一行原歌词");
    Selection selected;AssDialogue *first=nullptr;
    if(replace&&!context->ass->Events.empty()){
        // Keep the active identity alive, so undo restores a usable selection.
        // Clearing selection before committing would erase it from the previous
        // native undo snapshot as well.
        auto reuse=context->selectionController->GetActiveLine();if(!reuse)reuse=&context->ass->Events.front();
        context->selectionController->SetSelectionAndActive({reuse},reuse);
        for(auto it=context->ass->Events.begin();it!=context->ass->Events.end();){auto row=&*it++;if(row!=reuse){context->ass->Events.erase(context->ass->Events.iterator_to(*row));delete row;}}
        int id=reuse->Id;static_cast<AssDialogueBase&>(*reuse)=static_cast<AssDialogueBase const&>(*prepared.front());reuse->Id=id;prepared.erase(prepared.begin());first=reuse;selected.insert(reuse);
    }
    if(!first)first=prepared.front().get();for(auto& line:prepared){selected.insert(line.get());context->ass->Events.push_back(*line.release());}
    fields_dirty=false;context->ass->Commit(L"导入原歌词（估算粗轴）",AssFile::COMMIT_DIAG_ADDREM|AssFile::COMMIT_DIAG_FULL);context->selectionController->SetSelectionAndActive(std::move(selected),first);RefreshLine();SetStatus(L"已导入原歌词，保留空格与标点。可以转录匹配，或复用已有转录；时间仍待校准。");
}

void StudioPanel::ImportProject() {
    wxFileDialog dialog(this,L"打开声稿工程","","",L"声稿工程 (*.json)|*.json",wxFD_OPEN|wxFD_FILE_MUST_EXIST);
    if(dialog.ShowModal()!=wxID_OK)return;
    OpenProject(std::filesystem::path(dialog.GetPath().ToStdWstring()));
}

bool StudioPanel::OpenProject(std::filesystem::path const& project_file) {
    auto data=read_json(project_file);auto& object=static_cast<json::Object&>(data);
    auto list=object.find("lines");if(list==object.end())throw std::runtime_error("不是有效的声稿工程 JSON");
    auto const& imported=static_cast<json::Array const&>(list->second);
    if(imported.empty())throw std::runtime_error("工程没有歌词行");
    for(auto const& line:imported)studio_document::karaoke(line);
    auto media=field(object,"media");auto video=field(object,"video");
    auto history=object.find("api_history");
    if(history!=object.end())static_cast<json::Array const&>(history->second);
    if(pid)throw std::runtime_error("请先等待或取消后台任务再打开工程");
    if(!PrepareClose()||context->subsController->TryToClose()==wxCANCEL)return false;
    context->project->CloseSubtitles();
    AssDialogue *first=&*context->ass->Events.begin();bool initial=true;
    for(auto const& line:imported){
        AssDialogue *target=first;
        if(!initial){target=new AssDialogue;context->ass->Events.push_back(*target);}
        WriteLine(target,line,true);initial=false;
    }
    if(history!=object.end())context->ass->SetScriptInfo("Shengao API History",single_line_json(history->second));
    context->ass->Commit(L"打开声稿工程",AssFile::COMMIT_DIAG_ADDREM|AssFile::COMMIT_DIAG_FULL|AssFile::COMMIT_EXTRADATA|AssFile::COMMIT_SCRIPTINFO);
    context->selectionController->SetSelectionAndActive(Selection{first},first);
    if(!video.empty()){
        auto path=std::filesystem::u8path(video);
        if(path.is_relative())path=project_file.parent_path()/path;
        if(std::filesystem::exists(path))context->project->LoadVideo(agi::fs::path(path));
    }
    if(!media.empty()){
        auto path=std::filesystem::u8path(media);
        if(path.is_relative())path=project_file.parent_path()/path;
        if(std::filesystem::exists(path)){context->project->LoadAudio(agi::fs::path(path));}
        else wxMessageBox(L"工程引用的媒体不存在，请通过音频／视频菜单重新选择。",L"工程媒体",wxOK|wxICON_INFORMATION,this);
    }
    RefreshLine();SetStatus(L"声稿工程已打开。保存 ASS 可继续保留注音与接口资料。");return true;
}

void StudioPanel::Configure() {
    json::Object request;request["action"]="settings";Launch(std::move(request));
}

void StudioPanel::ShowConfigure(json::UnknownElement const& settings) {
    auto const& saved=static_cast<json::Object const&>(settings);
    wxDialog dialog(this,wxID_ANY,L"API 设置 · 密钥使用 Windows 加密保存",wxDefaultPosition,FromDIP(wxSize(540,520)));
    auto sizer=new wxBoxSizer(wxVERTICAL);auto choice=new wxChoice(&dialog,wxID_ANY);
    choice->Append("ElevenLabs");choice->Append(L"Microsoft MAI · Azure Speech");choice->Append("DeepSeek");choice->SetSelection(0);
    auto key=new wxTextCtrl(&dialog,wxID_ANY,"",wxDefaultPosition,wxDefaultSize,wxTE_PASSWORD);
    auto endpoint=new wxTextCtrl(&dialog,wxID_ANY);auto model=new wxTextCtrl(&dialog,wxID_ANY,"deepseek-flash");
    auto saved_note=new wxStaticText(&dialog,wxID_ANY,"");
    auto forget=new wxCheckBox(&dialog,wxID_ANY,L"删除此服务已保存的密钥");
    auto update=[&](){
        auto name=choice->GetSelection()==2?"deepseek":choice->GetSelection()==1?"mai":"elevenlabs";
        auto found=saved.find(name);json::Object empty;
        auto const& config=found==saved.end()?empty:static_cast<json::Object const&>(found->second);
        key->Clear();forget->SetValue(false);
        saved_note->SetLabel(json_bool(config,"has_key")?L"此服务已保存密钥。":L"此服务尚未保存密钥；也可使用环境变量。");
        endpoint->ChangeValue(display(field(config,"endpoint")));endpoint->Enable(choice->GetSelection()==1);
        model->ChangeValue(display(field(config,"model","deepseek-flash")));model->Enable(choice->GetSelection()==2);
    };
    choice->Bind(wxEVT_CHOICE,[&](wxCommandEvent&){update();});update();
    sizer->Add(new wxStaticText(&dialog,wxID_ANY,L"选择要配置的服务；密钥留空会保留已有密钥。"),0,wxALL,12);
    sizer->Add(choice,0,wxEXPAND|wxALL,10);sizer->Add(new wxStaticText(&dialog,wxID_ANY,"API Key"),0,wxLEFT,10);sizer->Add(key,0,wxEXPAND|wxALL,10);
    sizer->Add(saved_note,0,wxLEFT|wxRIGHT,10);sizer->Add(forget,0,wxALL,10);
    sizer->Add(new wxStaticText(&dialog,wxID_ANY,L"MAI：Azure Speech 资源根地址"),0,wxLEFT,10);sizer->Add(endpoint,0,wxEXPAND|wxALL,10);
    sizer->Add(new wxStaticText(&dialog,wxID_ANY,L"DeepSeek：模型名称"),0,wxLEFT,10);sizer->Add(model,0,wxEXPAND|wxALL,10);
    sizer->Add(dialog.CreateButtonSizer(wxOK|wxCANCEL),0,wxEXPAND|wxALL,10);dialog.SetSizer(sizer);
    if(dialog.ShowModal()!=wxID_OK)return;
    json::Object request;request["action"]="configure";request["provider"]=choice->GetSelection()==2?"deepseek":choice->GetSelection()==1?"mai":"elevenlabs";
    request["key"]=utf8(key->GetValue());request["forget"]=forget->GetValue();
    if(choice->GetSelection()==1&&!endpoint->GetValue().empty())request["endpoint"]=utf8(endpoint->GetValue());
    if(choice->GetSelection()==2&&!model->GetValue().empty())request["model"]=utf8(model->GetValue());
    key->Clear();Launch(std::move(request));
}

void StudioPanel::Start(std::string const& task,bool selected) {
    try {
        if(pid)throw std::runtime_error("已有后台任务运行，请先等待完成或取消");
        if(!FlushChanges())return;
        json::Object request;request["action"]=task;request["provider"]=task=="annotate"?"deepseek":task=="align"?"elevenlabs":provider->GetSelection()==1?"mai":"elevenlabs";request["language"]="ja";
        request["range_mode"]=task=="align"&&local_range->GetValue()?"selection":"full";
        auto media=context->project->AudioName();if(media.empty())media=context->project->VideoName();request["media"]=media.u8string().empty()?std::string():utf8(wxString(media.wstring()));
        auto lines=task=="transcribe"?json::Array():ReadLines(selected);
        if(task!="transcribe"&&lines.empty())throw std::runtime_error("请先导入或选中歌词");
        snapshots.clear();for(auto const& line:lines){auto const& object=static_cast<json::Object const&>(line);snapshots[std::stoi(field(object,"id"))]=encode(line);}
        request["lines"]=std::move(lines);
        if(wxMessageBox(L"将向所选服务提交音频或歌词，并按账户计费。结果完成后先审核再应用。继续？",L"云端处理",wxYES_NO|wxICON_QUESTION,this)!=wxYES)return;
        Launch(std::move(request));
    }catch(std::exception const& e){wxMessageBox(display(e.what()),L"声稿",wxOK|wxICON_ERROR,this);}
}

void StudioPanel::Launch(json::Object request) {
    if(pid)throw std::runtime_error("已有后台任务运行，请先等待完成或取消");
    action=json_bool(request,"preview")?"preview":field(request,"action");
    auto home=test_worker_home.empty()?std::filesystem::path(wxStandardPaths::Get().GetUserDataDir().ToStdWstring()):test_worker_home;
    std::filesystem::create_directories(home/"tasks");
    task_dir=home/"tasks"/std::to_string(wxGetUTCTimeMillis().GetValue());std::filesystem::create_directory(task_dir);result_file=task_dir/"result.json";
    RecordTask(request);
    auto executable=std::filesystem::path(wxStandardPaths::Get().GetExecutablePath().ToStdWstring()).parent_path();
    std::vector<wxString> arguments;
    if(std::filesystem::exists(executable/"studio-worker.exe"))arguments.emplace_back((executable/"studio-worker.exe").wstring());
    else {
        auto root=executable;bool found=false;
        for(int i=0;i<6;++i){if(std::filesystem::exists(root/"backend/worker_entry.py")&&std::filesystem::exists(root/".venv/Scripts/python.exe")){found=true;break;}root=root.parent_path();}
        if(!found)throw std::runtime_error("未找到 studio-worker.exe，请使用完整的软件包");
        arguments.emplace_back((root/".venv/Scripts/python.exe").wstring());arguments.emplace_back((root/"backend/worker_entry.py").wstring());
    }
    arguments.emplace_back("--request");arguments.emplace_back("-");arguments.emplace_back("--result");arguments.emplace_back(result_file.wstring());arguments.emplace_back("--home");arguments.emplace_back(home.wstring());
    std::vector<wchar_t const*> argv;for(auto const& argument:arguments)argv.push_back(argument.wc_str());argv.push_back(nullptr);
    process=new wxProcess(this);process->Redirect();pid=wxExecute(argv.data(),wxEXEC_ASYNC|wxEXEC_HIDE_CONSOLE|wxEXEC_MAKE_GROUP_LEADER,process);
    if(!pid){delete process;process=nullptr;throw std::runtime_error("无法启动后台工作进程");}
    worker_payload=encode(json::UnknownElement(std::move(request)));worker_stderr.clear();request_bytes=worker_payload.size();request_sent=0;
    // wxMSW stdin pipes are nonblocking. A write larger than the available pipe
    // capacity can succeed with zero bytes. Retain the unsent bytes until a
    // later timer tick; never send EOF before the entire UTF-8 JSON arrives.
    timer.Start(30);SendWorkerRequest();
    SetStatus(L"后台任务已启动；你可以继续试听和校轴。");UpdateBusy();
}

void StudioPanel::Poll(wxTimerEvent&) {
    DrainWorker();SendWorkerRequest();
    UpdateBusy();
    auto progress=std::filesystem::path(result_file.wstring()+L".progress.json");
    if(std::filesystem::exists(progress)){try{auto value=read_json(progress);auto const& object=static_cast<json::Object const&>(value);SetStatus(display(field(object,"message")));}catch(...) {}}
}

void StudioPanel::SendWorkerRequest() {
    if(!process||worker_payload.empty())return;
    auto stream=process->GetOutputStream();
    for(int n=0;n<16&&request_sent<request_bytes;++n){
        stream->Reset();
        auto count=std::min<size_t>(1024,request_bytes-request_sent);
        stream->Write(worker_payload.data()+request_sent,count);
        auto written=stream->LastWrite();request_sent+=written;
        if(stream->GetLastError()==wxSTREAM_EOF){process->CloseOutput();worker_payload.clear();return;}
        if(written<count)break; // Full pipe: continue on the next event tick.
    }
    if(request_sent==request_bytes){process->CloseOutput();worker_payload.clear();timer.Start(300);}
}

void StudioPanel::DrainWorker() {
    char buffer[1024];
    for(int n=0;process&&n<32&&process->IsInputAvailable();++n)process->GetInputStream()->Read(buffer,sizeof(buffer));
    for(int n=0;process&&n<32&&process->IsErrorAvailable();++n){auto stream=process->GetErrorStream();stream->Read(buffer,sizeof(buffer));worker_stderr.append(buffer,stream->LastRead());if(worker_stderr.size()>16384)worker_stderr.erase(0,worker_stderr.size()-16384);}
}

void StudioPanel::EndProcess(wxProcessEvent& event) {
    timer.Stop();DrainWorker();worker_exit=event.GetExitCode();pid=0;delete process;process=nullptr;worker_payload.clear();UpdateBusy();
    bool returned=std::filesystem::is_regular_file(result_file);
    // Persist only safe transport facts, never stdout/stderr, request JSON or keys.
    std::string diagnostic=request_sent<request_bytes?"incomplete_request":worker_stderr.find("ModuleNotFoundError")!=std::string::npos?"missing_module":worker_stderr.find("JSONDecodeError")!=std::string::npos?"invalid_request":returned?"result_received":"worker_exited_without_result";
    worker_stderr.clear();
    try{json::Object info;info["exit_code"]=worker_exit;info["request_bytes"]=int64_t(request_bytes);info["sent_bytes"]=int64_t(request_sent);info["result_present"]=returned;info["diagnostic"]=diagnostic;std::ofstream output(task_dir/"process.json",std::ios::binary);agi::JsonWriter::Write(info,output);}catch(...){}
    try {
        if(!returned){
            auto message=diagnostic=="incomplete_request"?"任务数据未完整送达后台，本次未能正常启动处理。":diagnostic=="missing_module"?"后台运行库缺少组件，请重新解压完整软件包。":"后台进程意外退出，没有返回结果。";
            throw std::runtime_error(std::string(message)+"退出代码："+std::to_string(worker_exit)+"；诊断已保存在任务记录中。程序不会自动重新提交云端请求。");
        }
        auto result=read_json(result_file);auto const& object=static_cast<json::Object const&>(result);
        if(!json_bool(object,"ok"))throw std::runtime_error(field(object,"message","后台处理失败"));
        if(action=="settings"){ShowConfigure(object.at("settings"));return;}
        if(action=="configure"){SetStatus(L"API 设置已加密保存。");return;}
        if(action=="preview"){
            LoadPreview(std::filesystem::u8path(field(object,"output")));return;
        }
        if(action=="export"){SetStatus(L"导出完成："+display(field(object,"output")));return;}
        pending_task=task_dir;has_pending_result=true;UpdateBusy();
        SetStatus(json_bool(object,"partial")?display(field(object,"message")):wxString(L"结果已就绪 · 点击“审核结果”查看。你可以继续编辑；本机记录已保留。"));
    }catch(std::exception const& e){SetStatus(display(e.what()));if(!test_worker)wxMessageBox(display(e.what()),L"后台任务结果",wxOK|wxICON_INFORMATION,this);}
}

#include "studio_review.inc"

std::pair<int,int> StudioPanel::ApplyReviewed(json::UnknownElement const& value,std::vector<bool> const& checked) {
    auto const& result=static_cast<json::Object const&>(value);
    auto const& suggestions=static_cast<json::Array const&>(result.at("suggestions"));
    auto task_id=field(result,"task_id");
    if(!task_id.empty()){
        auto stored=context->ass->GetScriptInfo("Shengao API History");
        if(!stored.empty()){auto history=decode(std::string(stored));for(auto const& item:static_cast<json::Array const&>(history))if(field(static_cast<json::Object const&>(item),"task_id")==task_id)throw std::runtime_error("这份结果已经应用；如需重新审核，请先撤销原应用，避免重复添加歌词");}
    }
    if(checked.size()!=suggestions.size())throw std::runtime_error("审核选择与建议数量不一致");
    int applied=0,skipped=0;AssDialogue *first=nullptr;
    // Validate every checked suggestion before changing any existing line.
    for(size_t i=0;i<suggestions.size();++i)if(checked[i])studio_document::karaoke(suggestions[i]);
    for(size_t i=0;i<suggestions.size();++i){if(!checked[i])continue;auto const& data=suggestions[i];auto const& object=static_cast<json::Object const&>(data);AssDialogue *line=nullptr;
        auto match=object.find("match");if((action=="match"||action=="transcribe_match")&&match!=object.end()&&field(static_cast<json::Object const&>(match->second),"status")=="protected"){++skipped;continue;}
        if(action=="transcribe"){line=new AssDialogue;context->ass->Events.push_back(*line);}
        else{int id=std::stoi(field(object,"id"));line=find_line(context,id);if(!line||((fields_dirty||timing_dirty)&&id==active_id)){++skipped;continue;}auto current=ReadLine(line);auto const& current_object=static_cast<json::Object const&>(current);bool protected_segment=action=="segment"&&json_bool(current_object,"reviewed");if(action=="segment"||action=="refine")for(auto const& unit:static_cast<json::Array const&>(current_object.at("units")))protected_segment|=json_bool(static_cast<json::Object const&>(unit),"locked");if(encode(current)!=snapshots[id]||json_bool(current_object,"locked")||protected_segment){++skipped;continue;}}
        WriteLine(line,data,true);if(!first)first=line;++applied;
    }
    if(applied){
        json::Array history;
        auto stored=context->ass->GetScriptInfo("Shengao API History");
        if(!stored.empty()){try{auto previous=decode(std::string(stored));history=std::move(static_cast<json::Array&>(previous));}catch(...) {}}
        history.emplace_back(decode(encode(value)));
        context->ass->SetScriptInfo("Shengao API History",single_line_json(json::UnknownElement(std::move(history))));
        context->ass->Commit(L"应用审核后的自动建议",AssFile::COMMIT_DIAG_ADDREM|AssFile::COMMIT_DIAG_FULL|AssFile::COMMIT_EXTRADATA|AssFile::COMMIT_SCRIPTINFO);
        if(first&&!fields_dirty)context->selectionController->SetSelectionAndActive(Selection{first},first);
        if(!fields_dirty)RefreshLine();}
    if(applied&&has_pending_result&&!task_id.empty()&&task_id==pending_task.filename().string()){has_pending_result=false;UpdateBusy();}
    return {applied,skipped};
}

void StudioPanel::LoadPreview(std::filesystem::path const& path) {
    auto provider=context->project->VideoProvider();
    if(!provider)throw std::runtime_error("视频已关闭，请重新打开后刷新预览");
    AssFile preview;AssSubtitleFormat format;
    format.ReadFile(&preview,agi::fs::path(path.wstring()),context->project->Timecodes(),"UTF-8");
    provider->LoadSubtitles(&preview);
    int frame=context->videoController->GetFrameN();
    provider->RequestFrame(frame,context->videoController->TimeAtFrame(frame));
    preview_active=true;preview_stale=false;UpdateOverview();
    SetStatus(L"已显示注音成品预览。修改歌词后请再次刷新。");
}

void StudioPanel::Export(bool resolved) {
    try {
        if(!FlushChanges())return;
        auto export_lines=ReadLines(false);
        if(export_lines.empty())throw std::runtime_error("没有可导出的歌词，请先导入或识别");
        wxFileDialog dialog(this,L"导出字幕或工程","",resolved?"karaoke.ass":"project.json",
            resolved?L"ASS 字幕 (*.ass)|*.ass":L"声稿工程 (*.json)|*.json|SRT 字幕 (*.srt)|*.srt|歌词 (*.txt)|*.txt",wxFD_SAVE|wxFD_OVERWRITE_PROMPT);
        if(dialog.ShowModal()!=wxID_OK)return;
        json::Object request;request["action"]="export";request["lines"]=std::move(export_lines);request["output"]=utf8(dialog.GetPath());request["resolved"]=resolved;
        request["format"]=resolved?"ass":dialog.GetFilterIndex()==1?"srt":dialog.GetFilterIndex()==2?"txt":"json";
        request["show_ruby"]=show_ruby->GetValue();request["show_romaji"]=show_romaji->GetValue();request["show_translation"]=show_translation->GetValue();
        auto media=context->project->AudioName();if(media.empty())media=context->project->VideoName();
        request["media"]=utf8(wxString(media.wstring()));request["video"]=utf8(wxString(context->project->VideoName().wstring()));
        json::Array history;auto stored=context->ass->GetScriptInfo("Shengao API History");
        if(!stored.empty()){auto previous=decode(std::string(stored));history=std::move(static_cast<json::Array&>(previous));}
        request["api_history"]=std::move(history);Launch(std::move(request));
    }catch(std::exception const& e){wxMessageBox(display(e.what()),L"导出失败",wxOK|wxICON_ERROR,this);}
}

void StudioPanel::Preview() {
    if(!context->project->VideoProvider())throw std::runtime_error("请先打开视频；纯音频可在视频菜单创建空白视频用于预览");
    if(!FlushChanges())return;
    auto folder=std::filesystem::path(wxStandardPaths::Get().GetUserDataDir().ToStdWstring())/"preview";
    std::filesystem::create_directories(folder);
    json::Object request;request["action"]="export";request["format"]="ass";request["resolved"]=true;request["preview"]=true;
    request["show_ruby"]=show_ruby->GetValue();request["show_romaji"]=show_romaji->GetValue();request["show_translation"]=show_translation->GetValue();
    request["lines"]=ReadLines(false);request["output"]=utf8(wxString((folder/"current.ass").wstring()));Launch(std::move(request));
}

void StudioPanel::Cancel() {
    if(pid){std::ofstream cancel(std::filesystem::path(result_file.wstring()+L".cancel"));cancel<<"cancel";SetStatus(L"正在取消；云端已接收的请求可能仍会计费。");cancel_button->Disable();}
}
