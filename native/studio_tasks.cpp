// Copyright (c) 2026 Shengao Karaoke Studio contributors. MIT.
#include "studio_panel.h"
#include "studio_workflow.h"
#include "ass_dialogue.h"
#include "ass_file.h"
#include "include/aegisub/context.h"
#include <wx/button.h>
#include <wx/datetime.h>
#include <wx/dialog.h>
#include <wx/listbox.h>
#include <wx/msgdlg.h>
#include <wx/sizer.h>
#include <wx/stattext.h>
#include <wx/stdpaths.h>
#include <wx/textctrl.h>
#include <algorithm>
#include <fstream>
#include <map>

namespace {
std::string text(json::Object const& object,char const *key){return studio_document::text(object,key);}
bool flag(json::Object const& object,char const *key){auto item=object.find(key);return item!=object.end()&&static_cast<json::Boolean const&>(item->second);}
json::UnknownElement read(std::filesystem::path const& file){std::ifstream stream(file,std::ios::binary);return agi::json_util::parse(stream);}
wxString show(std::string const& text){return wxString::FromUTF8(text);}
}

void StudioPanel::RecordTask(json::Object const& request) {
    auto kind=text(request,"action");
    if(kind!="transcribe"&&kind!="align"&&kind!="annotate"&&kind!="match"&&kind!="transcribe_match"&&kind!="segment"&&kind!="refine")return;
    // Deliberate whitelist. Never serialize the request or configuration keys.
    json::Object metadata;metadata["version"]=1;metadata["action"]=kind;
    metadata["provider"]=kind=="annotate"?"deepseek":kind=="align"?"elevenlabs":text(request,"provider");metadata["media"]=text(request,"media");
    auto media=text(request,"media");std::error_code media_error;auto media_path=std::filesystem::u8path(media);
    if(!media.empty()&&std::filesystem::is_regular_file(media_path,media_error)){
        auto size=std::filesystem::file_size(media_path,media_error);if(!media_error)metadata["media_size"]=std::to_string(size);
        auto stamp=std::filesystem::last_write_time(media_path,media_error);if(!media_error)metadata["media_stamp"]=std::to_string(stamp.time_since_epoch().count());
    }
    metadata["created_at"]=std::string(wxDateTime::Now().FormatISOCombined(' ').utf8_str());
    if(kind=="segment")metadata["mode"]=text(request,"mode");
    if(kind=="refine")for(auto key:{"use_llm","gap_ms","preserve_legacy","preserve_manual"})if(auto found=request.find(key);found!=request.end())metadata[key]=studio_workflow::copy(found->second);
    auto lines=request.find("lines");metadata["lines"]=lines==request.end()?json::UnknownElement(json::Array()):studio_workflow::copy(lines->second);
    {std::ofstream output(task_dir/"task.tmp",std::ios::binary);agi::JsonWriter::Write(metadata,output);if(!output)throw std::runtime_error("无法保存任务恢复资料");}
    std::filesystem::rename(task_dir/"task.tmp",task_dir/"task.json");
}

json::UnknownElement StudioPanel::RestoreTask(std::filesystem::path const& folder) {
    if(pid)throw std::runtime_error("已有任务运行，请等待完成或取消后恢复历史结果");
    auto metadata=read(folder/"task.json");auto const& request=static_cast<json::Object const&>(metadata);
    auto restored_action=text(request,"action");
    if(restored_action!="transcribe"&&restored_action!="align"&&restored_action!="annotate"&&restored_action!="match"&&restored_action!="transcribe_match"&&restored_action!="segment"&&restored_action!="refine")throw std::runtime_error("这条任务无法恢复为字幕建议");
    auto result=read(folder/"result.json");auto& object=static_cast<json::Object&>(result);
    if(!flag(object,"ok"))throw std::runtime_error("任务没有成功结果；可以查看失败详情，本操作不会重新提交云端");
    auto& suggestions=static_cast<json::Array&>(object.at("suggestions"));for(auto const& value:suggestions)studio_document::karaoke(value);
    snapshots.clear();
    if(restored_action!="transcribe"){
        auto const& originals=static_cast<json::Array const&>(request.at("lines"));
        std::map<std::string,int> original_counts;for(auto const& value:originals)++original_counts[studio_workflow::canonical(value)];
        std::map<std::string,std::vector<AssDialogue*>> current;
        for(auto& line:context->ass->Events)if(!line.Comment){auto data=ReadLine(&line);auto const& value=static_cast<json::Object const&>(data);if(!flag(value,"locked"))current[studio_workflow::canonical(data)].push_back(&line);}
        std::map<std::string,std::string> remapping;
        for(auto const& original:originals){auto key=studio_workflow::canonical(original);auto found=current.find(key);
            if(original_counts[key]!=1||found==current.end()||found->second.size()!=1)continue;
            auto line=found->second.front();auto const& value=static_cast<json::Object const&>(original);
            remapping[text(value,"id")]=std::to_string(line->Id);snapshots[line->Id]=studio_workflow::encode(ReadLine(line));
        }
        for(auto& value:suggestions){auto& suggestion=static_cast<json::Object&>(value);auto found=remapping.find(text(suggestion,"id"));suggestion["id"]=found==remapping.end()?"-1":found->second;}
    }
    action=restored_action;object["task_id"]=folder.filename().string();return result;
}

void StudioPanel::TaskHistory() {
    try {
        auto home=std::filesystem::path(wxStandardPaths::Get().GetUserDataDir().ToStdWstring())/"tasks";
        std::vector<std::filesystem::path> folders;
        if(std::filesystem::is_directory(home))for(auto const& entry:std::filesystem::directory_iterator(home))if(entry.is_directory()&&std::filesystem::is_regular_file(entry.path()/"task.json"))folders.push_back(entry.path());
        std::sort(folders.begin(),folders.end(),std::greater<std::filesystem::path>());if(folders.size()>50)folders.resize(50);
        wxDialog dialog(this,wxID_ANY,L"任务记录 · 查看详情或恢复已有结果",wxDefaultPosition,FromDIP(wxSize(920,600)));
        auto layout=new wxBoxSizer(wxVERTICAL);auto note=new wxStaticText(&dialog,wxID_ANY,L"只读取本机已有结果，不会重新请求云端。恢复后仍需审核；歌词已改变、锁定或匹配不唯一时会跳过。");note->Wrap(830);layout->Add(note,0,wxEXPAND|wxALL,16);
        auto body=new wxBoxSizer(wxHORIZONTAL);auto list=new wxListBox(&dialog,wxID_ANY,wxDefaultPosition,FromDIP(wxSize(330,-1)));auto details=new wxTextCtrl(&dialog,wxID_ANY,"",wxDefaultPosition,wxDefaultSize,wxTE_MULTILINE|wxTE_READONLY|wxHSCROLL);body->Add(list,0,wxEXPAND|wxRIGHT,12);body->Add(details,1,wxEXPAND);layout->Add(body,1,wxEXPAND|wxLEFT|wxRIGHT,16);
        std::vector<bool> successful;
        for(auto const& folder:folders){
            try{auto value=read(folder/"task.json");auto const& meta=static_cast<json::Object const&>(value);auto kind=text(meta,"action");bool ok=false;wxString state=L"暂无结果";
                if(std::filesystem::is_regular_file(folder/"result.json")){auto result=read(folder/"result.json");auto const& data=static_cast<json::Object const&>(result);ok=flag(data,"ok");state=ok?(flag(data,"partial")?L"部分完成":L"成功"):L"失败／已取消";}
                wxString name=kind=="transcribe"?L"识别":kind=="align"?L"对齐":kind=="match"?L"本地匹配":kind=="transcribe_match"?L"转录并分行":kind=="segment"?L"本地分词":kind=="refine"?L"转录辅助复核":L"注音";list->Append(show(text(meta,"created_at"))+L"  "+name+L" · "+state);successful.push_back(ok);
            }catch(...){list->Append(L"记录损坏 · "+wxString(folder.filename().wstring()));successful.push_back(false);}
        }
        auto buttons=new wxBoxSizer(wxHORIZONTAL);auto restore=new wxButton(&dialog,wxID_ANY,L"恢复成功结果并审核");restore->Enable(false);buttons->Add(restore,1,wxRIGHT,10);buttons->Add(new wxButton(&dialog,wxID_CANCEL,L"关闭"));layout->Add(buttons,0,wxEXPAND|wxALL,16);
        auto select=[&](int index){if(index<0||index>=int(folders.size()))return;restore->Enable(successful[index]&&!pid);
            try{auto meta=read(folders[index]/"task.json");std::string content="任务资料\n"+studio_workflow::encode(meta);
                if(std::filesystem::is_regular_file(folders[index]/"result.json")){auto result=read(folders[index]/"result.json");content+="\n\n结果 / 错误诊断\n"+studio_workflow::encode(result);}
                if(std::filesystem::is_regular_file(folders[index]/"process.json"))content+="\n\n后台进程诊断\n"+studio_workflow::encode(read(folders[index]/"process.json"));
                details->ChangeValue(show(content));
            }catch(std::exception const& e){details->ChangeValue(show(e.what()));}
        };
        list->Bind(wxEVT_LISTBOX,[&](wxCommandEvent& event){select(event.GetSelection());});
        restore->Bind(wxEVT_BUTTON,[&](wxCommandEvent&){if(list->GetSelection()>=0&&successful[list->GetSelection()])dialog.EndModal(wxID_OK);});
        if(!folders.empty()){list->SetSelection(0);select(0);}else details->ChangeValue(L"还没有可恢复任务。新发起的识别、对齐和注音任务会记录在这里。");
        dialog.SetSizer(layout);if(dialog.ShowModal()!=wxID_OK)return;
        auto result=RestoreTask(folders.at(list->GetSelection()));Review(result);
    }catch(std::exception const& e){wxMessageBox(show(e.what()),L"任务记录",wxOK|wxICON_INFORMATION,this);}
}

void StudioPanel::ReviewPending() {
    if(!has_pending_result)return;
    try{auto result=RestoreTask(pending_task);Review(result);}
    catch(std::exception const& error){wxMessageBox(show(error.what()),L"审核结果",wxOK|wxICON_INFORMATION,this);}
}
