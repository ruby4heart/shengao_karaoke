// Copyright (c) 2026 Shengao Karaoke Studio contributors. MIT.
#pragma once
#include "studio_workflow.h"
#include <array>
#include <iterator>

namespace studio_editing {
inline void manual(json::Object& line) {
    line["reviewed"]=false;
    auto found=line.find("match");if(found!=line.end()){
        auto& info=static_cast<json::Object&>(found->second);info["status"]="manual";info["reason"]="已人工调整词组或候选位置，请试听校准";info.erase("candidates");
    }
}
inline json::UnknownElement split(json::UnknownElement const& input,int row,std::vector<std::string> const& parts,std::vector<std::string> const& readings={}) {
    auto result=studio_workflow::copy(input);auto& line=static_cast<json::Object&>(result);auto& units=static_cast<json::Array&>(line.at("units"));
    if(row<0||row>=int(units.size())||parts.size()<2)throw std::runtime_error("请选择词组，并用 | 分为至少两组");
    auto const& old=static_cast<json::Object const&>(units[row]);std::string joined;for(auto const& part:parts){if(part.empty())throw std::runtime_error("词组不能留空");joined+=part;}
    if(joined!=studio_document::text(old,"text"))throw std::runtime_error("拆分必须完整保留原词，不能增删文字或空格");
    if(!readings.empty()&&readings.size()!=parts.size())throw std::runtime_error("假名组数须与原文组数一致");
    int start=studio_document::time(old,"start"),end=studio_document::time(old,"end"),ticks=(end-start)/10;
    if(ticks<int(parts.size()))throw std::runtime_error("该词时长不足，每个新词组至少需要 10 ms");
    std::vector<int> weights;int total=0;for(auto const& part:parts){int count=0;for(unsigned char c:part)if((c&0xc0)!=0x80)++count;weights.push_back(std::max(1,count));total+=weights.back();}
    json::Array divided;int prior=start,offset=0;
    for(size_t i=0;i<parts.size();++i){offset+=weights[i];int finish=i+1==parts.size()?end:std::clamp(start+int(std::llround(double(ticks)*offset/total))*10,prior+10,end-int(parts.size()-i-1)*10);
        json::Object unit;unit["text"]=parts[i];unit["kana"]=readings.empty()?"":readings[i];unit["romaji"]="";unit["start"]=prior;unit["end"]=finish;unit["source"]="estimated";auto protect=old.find("locked");unit["locked"]=protect!=old.end()&&static_cast<json::Boolean const&>(protect->second);divided.emplace_back(std::move(unit));prior=finish;
    }
    units.erase(units.begin()+row);units.insert(units.begin()+row,std::make_move_iterator(divided.begin()),std::make_move_iterator(divided.end()));manual(line);studio_document::karaoke(result);return result;
}
inline json::UnknownElement merge(json::UnknownElement const& input,int row) {
    auto result=studio_workflow::copy(input);auto& line=static_cast<json::Object&>(result);auto& units=static_cast<json::Array&>(line.at("units"));
    if(row<0||row+1>=int(units.size()))throw std::runtime_error("请选择需要与下一组合并的词");
    auto& first=static_cast<json::Object&>(units[row]);auto const& second=static_cast<json::Object const&>(units[row+1]);
    json::Array highlights;bool complete=!studio_document::text(first,"kana").empty()&&!studio_document::text(second,"kana").empty();
    if(complete)for(auto const* item:std::array<json::Object const*,2>{&first,&second}){
        auto found=item->find("highlights");if(found!=item->end()&&!static_cast<json::Array const&>(found->second).empty()){
            for(auto const& part:static_cast<json::Array const&>(found->second))highlights.emplace_back(studio_workflow::copy(part));
        }else{json::Object part;for(auto key:{"kana","start","end","source"})part[key]=studio_workflow::copy(item->at(key));highlights.emplace_back(std::move(part));}
    }
    first["text"]=studio_document::text(first,"text")+studio_document::text(second,"text");
    first["kana"]=complete?studio_document::text(first,"kana")+studio_document::text(second,"kana"):"";
    auto a=studio_document::text(first,"romaji"),b=studio_document::text(second,"romaji");first["romaji"]=a.empty()?b:b.empty()?a:a+" "+b;
    first["end"]=studio_document::time(second,"end");first["highlights"]=std::move(highlights);first["source"]="manual";
    bool protect=false;for(auto const* item:std::array<json::Object const*,2>{&first,&second}){auto found=item->find("locked");if(found!=item->end())protect|=static_cast<json::Boolean const&>(found->second);}first["locked"]=protect;
    units.erase(units.begin()+row+1);manual(line);studio_document::karaoke(result);return result;
}
inline json::UnknownElement candidate(json::UnknownElement const& input,json::UnknownElement const& choice) {
    auto result=studio_workflow::copy(input);auto& line=static_cast<json::Object&>(result);auto const& selected=static_cast<json::Object const&>(choice);
    for(auto key:{"start","end","units"})line[key]=studio_workflow::copy(selected.at(key));
    manual(line);auto& info=static_cast<json::Object&>(line.at("match"));for(auto key:{"score","coverage","recognized","method"}){auto found=selected.find(key);if(found!=selected.end())info[key]=studio_workflow::copy(found->second);}
    studio_document::karaoke(result);return result;
}
}
