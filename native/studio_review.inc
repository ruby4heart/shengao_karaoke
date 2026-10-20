// Copyright (c) 2026 Shengao Karaoke Studio contributors. MIT.
void StudioPanel::Review(json::UnknownElement const& value,std::function<int(wxDialog&)> const& inspect) {
    auto edited=studio_workflow::copy(value);
    auto& result=static_cast<json::Object&>(edited);auto& suggestions=static_cast<json::Array&>(result.at("suggestions"));
    auto baseline=studio_workflow::copy(result.at("suggestions"));auto const& originals=static_cast<json::Array const&>(baseline);
    wxDialog dialog(this,wxID_ANY,action=="refine"?L"读音二次复核 · 试听后勾选应用":L"审核与试听 · 原歌词不变，勾选后才应用",wxDefaultPosition,FromDIP(wxSize(850,640)),wxDEFAULT_DIALOG_STYLE|wxRESIZE_BORDER);dialog.SetMinSize(FromDIP(wxSize(700,540)));dialog.SetFont(studio_ui::font());
    auto layout=new wxBoxSizer(wxVERTICAL);auto list=new wxCheckListBox(&dialog,wxID_ANY);
    auto preview=new wxTextCtrl(&dialog,wxID_ANY,"",wxDefaultPosition,FromDIP(wxSize(-1,235)),wxTE_MULTILINE|wxTE_READONLY);
    list->SetMinSize(FromDIP(wxSize(0,80)));preview->SetMinSize(FromDIP(wxSize(0,100)));
    auto position=new wxChoice(&dialog,wxID_ANY);auto controls=new wxBoxSizer(wxHORIZONTAL);
    controls->Add(new wxStaticText(&dialog,wxID_ANY,action=="refine"?L"原行时间":L"候选位置"),0,wxALIGN_CENTER_VERTICAL|wxRIGHT,8);controls->Add(position,1,wxRIGHT,10);
    auto play=new wxButton(&dialog,wxID_ANY,L"试听当前建议");auto stop=new wxButton(&dialog,wxID_ANY,L"停止");controls->Add(play,0,wxRIGHT,6);controls->Add(stop,0);
    list->SetName(L"review-rows");position->SetName(L"review-candidates");preview->SetName(L"review-details");play->SetName(L"review-play");stop->SetName(L"review-stop");
    auto clock=[](int ms){return wxString::Format(L"%02d:%02d.%02d",ms/60000,ms/1000%60,ms/10%100);};
    auto interval=[&](json::Object const& row){return clock(number(row.at("start")))+L" → "+clock(number(row.at("end")));};
    std::vector<bool> eligible,confident;std::vector<int> choices(suggestions.size(),0);
    auto row_label=[&](int index){auto const& row=static_cast<json::Object const&>(suggestions[index]);auto found=row.find("match");wxString badge;
        if(found!=row.end()){auto const& info=static_cast<json::Object const&>(found->second);auto state=field(info,"status");badge=state=="matched"?L"匹配":state=="uncertain"?L"待确认":state=="unmatched"?L"未匹配":state=="protected"?L"保护":state=="manual"?L"人工调整":L"";auto score=info.find("score");if(score!=info.end())badge+=wxString::Format(L" %.0f%%",std::stod(encode(score->second))*100);}
        if(action=="refine")badge=L"读音 / 短空隙待试听";
        return (eligible[index]?wxString():wxString(L"[跳过] "))+(badge.empty()?wxString():L"["+badge+L"] ")+interval(row)+L"  "+display(field(row,"text"));};
    for(size_t i=0;i<suggestions.size();++i){auto const& row=static_cast<json::Object const&>(suggestions[i]);bool allowed=action=="transcribe";
        if(!allowed){int id=std::stoi(field(row,"id"));if(auto line=find_line(context,id)){auto current=ReadLine(line);auto const& object=static_cast<json::Object const&>(current);allowed=encode(current)==snapshots[id]&&!json_bool(object,"locked")&&!((fields_dirty||timing_dirty)&&id==active_id);
            if(action=="segment"||action=="refine"){if(action=="segment")allowed&=!json_bool(object,"reviewed");for(auto const& unit:static_cast<json::Array const&>(object.at("units")))allowed&=!json_bool(static_cast<json::Object const&>(unit),"locked");}
        }}
        bool reliable=true;auto match=row.find("match");if(match!=row.end()){auto const& info=static_cast<json::Object const&>(match->second);auto state=field(info,"status");if(state=="protected"&&(action=="match"||action=="transcribe_match"))allowed=false;if(action=="match"||action=="transcribe_match")reliable=state.empty()||state=="matched"||state=="manual";}
        if(action=="refine")reliable=false;
        eligible.push_back(allowed);confident.push_back(reliable);list->Append(row_label(i));list->Check(i,allowed&&reliable);
    }
    auto show=[&](int index,bool reload_choices=true){if(index<0||index>=int(suggestions.size()))return;auto const& row=static_cast<json::Object const&>(suggestions[index]);
        if(reload_choices){position->Clear();position->Append(L"原始建议 · "+interval(static_cast<json::Object const&>(originals[index])));auto const& original=static_cast<json::Object const&>(originals[index]);auto match=original.find("match");if(action!="refine"&&match!=original.end()){auto const& info=static_cast<json::Object const&>(match->second);auto found=info.find("candidates");if(found!=info.end())for(auto const& item:static_cast<json::Array const&>(found->second))position->Append(interval(static_cast<json::Object const&>(item)));}position->SetSelection(choices[index]);position->Enable(eligible[index]&&position->GetCount()>1);}
        std::string detail="原歌词（保留空格与标点）："+field(row,"text")+"\n";
        if(action!="refine")detail+="假名："+field(row,"kana")+"\n罗马音："+field(row,"romaji")+"\n译文："+field(row,"translation")+"\n";
        auto match=row.find("match");if(action!="refine"&&match!=row.end()){auto const& info=static_cast<json::Object const&>(match->second);if(!info.empty())detail+="\n识别对应："+field(info,"recognized")+"\n匹配方式："+(field(info,"method")=="reading"?"读音辅助":"原文文字")+"\n"+field(info,"reason")+"\n分数是文字对应程度；时间仍需试听校准。\n";}
        if(action=="segment")detail+="\n本地词典读音是建议；特殊唱法可修改假名或使用 DeepSeek。黄色估算时间需要校准。\n";
        if(auto found=row.find("reading_review");found!=row.end()){
            auto const& review=static_cast<json::Object const&>(found->second);detail+="\n二次复核依据："+field(review,"recognized")+"\n分析方式："+(field(review,"method")=="local"?"离线词典＋转录候选":"DeepSeek＋转录及上下文")+"\n";
            size_t changed=0,manual=0,total=0;
            if(auto words=review.find("words");words!=review.end())for(auto const& value:static_cast<json::Array const&>(words->second)){
                auto const& word=static_cast<json::Object const&>(value);++total;auto basis=field(word,"basis");manual+=basis=="manual";
                bool kana_changed=field(word,"before")!=field(word,"suggested"),roman_changed=field(word,"before_romaji")!=field(word,"suggested_romaji");if(!kana_changed&&!roman_changed)continue;++changed;
                detail+="● "+field(word,"text")+"："+(kana_changed?field(word,"before"):field(word,"before_romaji"))+" → "+(kana_changed?field(word,"suggested"):field(word,"suggested_romaji"))+"\n  转录："+field(word,"recognized")+"；词典："+field(word,"dictionary")+"；"+(basis=="manual"?"保留人工":basis=="transcript"?"转录候选":basis=="deepseek"?"DeepSeek 建议":"词典建议")+" "+field(word,"reason")+"\n";
            }
            detail+=changed?"":"未提出读音改动；请试听确认实际唱法。\n";
            detail+="未改动 "+std::to_string(total-changed)+" 个词，其中保留人工 "+std::to_string(manual)+" 个。\n";
            if(auto count=review.find("closed_gaps");count!=review.end())detail+="收拢短空隙："+std::to_string(number(count->second))+" 处（超过阈值的停顿、人工时间保留）\n";
            detail+=field(review,"notice")+"\n";
        }
        if(action=="refine")detail+="\n建议假名："+field(row,"kana")+"\n罗马音："+field(row,"romaji")+"\n译文："+field(row,"translation")+"\n";
        detail+="\n词组 / 假名音节 / 起止毫秒\n";
        for(auto const& item:static_cast<json::Array const&>(row.at("units"))){auto const& unit=static_cast<json::Object const&>(item);std::string reading=field(unit,"kana");auto parts=unit.find("highlights");if(parts!=unit.end()&&!static_cast<json::Array const&>(parts->second).empty()){reading.clear();for(auto const& part:static_cast<json::Array const&>(parts->second)){if(!reading.empty())reading+=" | ";reading+=field(static_cast<json::Object const&>(part),"kana");}}
            detail+=field(unit,"text")+" / "+reading+" / "+std::to_string(number(unit.at("start")))+" → "+std::to_string(number(unit.at("end")))+"\n";
        }
        preview->ChangeValue(display(detail));play->Enable(context->project->AudioProvider()!=nullptr);
    };
    list->Bind(wxEVT_LISTBOX,[&](wxCommandEvent& event){show(event.GetSelection());});
    position->Bind(wxEVT_CHOICE,[&](wxCommandEvent& event){int row=list->GetSelection(),index=event.GetSelection();if(row<0||!eligible[row])return;
        try{if(!index)suggestions[row]=studio_workflow::copy(originals[row]);else{auto const& original=static_cast<json::Object const&>(originals[row]);auto const& info=static_cast<json::Object const&>(original.at("match"));auto const& options=static_cast<json::Array const&>(info.at("candidates"));suggestions[row]=studio_editing::candidate(originals[row],options.at(index-1));}
            choices[row]=index;list->SetString(row,row_label(row));list->Check(row,index>0||confident[row]);show(row,false);
        }catch(std::exception const& error){wxMessageBox(display(error.what()),L"候选位置无效",wxOK|wxICON_INFORMATION,&dialog);}
    });
    bool played=false;play->Bind(wxEVT_BUTTON,[&](wxCommandEvent&){int index=list->GetSelection();if(index<0||!context->project->AudioProvider())return;StopAudition();auto const& row=static_cast<json::Object const&>(suggestions[index]);context->audioController->PlayRange(TimeRange(number(row.at("start")),number(row.at("end"))));played=true;});stop->Bind(wxEVT_BUTTON,[&](wxCommandEvent&){StopAudition();});
    auto checks=new wxBoxSizer(wxHORIZONTAL);auto strong=new wxButton(&dialog,wxID_ANY,L"仅勾选高可信／可应用行"),none=new wxButton(&dialog,wxID_ANY,L"全部取消勾选");checks->Add(strong,0,wxRIGHT,10);checks->Add(none,0);
    auto all=new wxButton(&dialog,wxID_ANY,L"勾选全部可应用行");all->SetName("review-select-all");checks->Add(all,0,wxLEFT,10);if(action=="refine")strong->Hide();all->Bind(wxEVT_BUTTON,[&](wxCommandEvent&){for(size_t i=0;i<suggestions.size();++i)list->Check(i,eligible[i]);});
    strong->Bind(wxEVT_BUTTON,[&](wxCommandEvent&){for(size_t i=0;i<suggestions.size();++i)list->Check(i,eligible[i]&&(confident[i]||choices[i]>0));});none->Bind(wxEVT_BUTTON,[&](wxCommandEvent&){for(size_t i=0;i<suggestions.size();++i)list->Check(i,false);});
    auto hint=new wxStaticText(&dialog,wxID_ANY,action=="refine"?L"先看转录依据和读音改动，再试听。所有读音建议默认不勾选；可手动勾选需要应用的行。\n确定后才写入工程，取消保持原内容；已确认的时间保持，注音按所选保护选项处理，锁定行跳过。":L"先选一行试听，副歌错位可切换候选。点确定后才应用；取消保持工程。\n没有合适候选时，回到本地匹配指定时间段。保护或处理中修改的行会跳过。");hint->Wrap(780);layout->Add(hint,0,wxEXPAND|wxALL,14);layout->Add(list,1,wxEXPAND|wxLEFT|wxRIGHT|wxBOTTOM,14);layout->Add(checks,0,wxLEFT|wxRIGHT|wxBOTTOM,14);layout->Add(controls,0,wxEXPAND|wxLEFT|wxRIGHT|wxBOTTOM,14);layout->Add(preview,1,wxEXPAND|wxLEFT|wxRIGHT|wxBOTTOM,14);layout->Add(dialog.CreateButtonSizer(wxOK|wxCANCEL),0,wxEXPAND|wxALL,14);dialog.SetSizer(layout);
    if(!suggestions.empty()){list->SetSelection(0);show(0);}int answer=inspect?inspect(dialog):dialog.ShowModal();if(played)context->audioController->Stop();if(answer!=wxID_OK)return;
    std::vector<bool> checked;for(size_t i=0;i<suggestions.size();++i)checked.push_back(list->IsChecked(i));auto [applied,skipped]=ApplyReviewed(edited,checked);
    SetStatus(wxString::Format(L"已应用 %d 行；跳过 %d 行。可撤销，请继续试听校准。",applied,skipped));
}
