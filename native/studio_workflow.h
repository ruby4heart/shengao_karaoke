// Copyright (c) 2026 Shengao Karaoke Studio contributors. MIT.
#pragma once
#include "studio_document.h"
#include <libaegisub/cajun/writer.h>
#include <libaegisub/json.h>
#include <algorithm>
#include <cstdint>
#include <regex>
#include <sstream>
#include <vector>

namespace studio_workflow {
inline std::string encode(json::UnknownElement const& value) {std::ostringstream out;agi::JsonWriter::Write(value,out);return out.str();}
inline json::UnknownElement copy(json::UnknownElement const& value) {std::istringstream in(encode(value));return agi::json_util::parse(in);}
inline std::string canonical(json::UnknownElement const& value) {
    auto clone=copy(value);auto& line=static_cast<json::Object&>(clone);line.erase("id");
    if(auto review=line.find("reading_review");review!=line.end()&&static_cast<json::Object const&>(review->second).empty())line.erase(review);
    if(auto found=line.find("units");found!=line.end())for(auto& value:static_cast<json::Array&>(found->second)){auto& unit=static_cast<json::Object&>(value);if(studio_document::text(unit,"reading_source").empty())unit.erase("reading_source");}
    return encode(clone);
}
inline std::string shape(json::UnknownElement const& value) {
    auto clone=copy(value);auto& line=static_cast<json::Object&>(clone);
    for(auto it=line.begin();it!=line.end();) {
        if(it->first!="text"&&it->first!="start"&&it->first!="end"&&it->first!="units")it=line.erase(it);else ++it;
    }
    for(auto& item:static_cast<json::Array&>(line.at("units"))){auto& unit=static_cast<json::Object&>(item);
        for(auto key:{"romaji","source","locked","reading_source"})unit.erase(key);
        auto found=unit.find("highlights");
        if(found!=unit.end()){
            auto& parts=static_cast<json::Array&>(found->second);
            if(parts.empty())unit.erase(found);else for(auto& part:parts)static_cast<json::Object&>(part).erase("source");
        }
    }
    return encode(clone);
}
inline json::UnknownElement shifted(json::UnknownElement const& value,int delta) {
    studio_document::karaoke(value);
    auto clone=copy(value);auto& line=static_cast<json::Object&>(clone);
    auto move=[&](json::Object& object){for(auto key:{"start","end"}){
        int64_t result=int64_t(studio_document::time(object,key))+delta;
        if(result<0||result>2147480000)throw std::runtime_error("偏移会产生负时间或超出支持范围，未应用任何修改");
        object[key]=result;
    }};
    move(line);line["reviewed"]=false;
    for(auto& value:static_cast<json::Array&>(line.at("units"))){auto& unit=static_cast<json::Object&>(value);move(unit);if(studio_document::text(unit,"source")!="estimated")unit["source"]="manual";
        auto parts=unit.find("highlights");if(parts!=unit.end())for(auto& part:static_cast<json::Array&>(parts->second)){
            auto& object=static_cast<json::Object&>(part);move(object);if(studio_document::text(object,"source")!="estimated")object["source"]="manual";
        }
    }
    studio_document::karaoke(clone);return clone;
}
struct Issue {std::string id,code,message;bool error=false;};
inline bool needs_mora(json::UnknownElement const& value){
    auto const& unit=static_cast<json::Object const&>(value);auto found=unit.find("highlights");if(found!=unit.end()&&!static_cast<json::Array const&>(found->second).empty())return false;
    auto reading=studio_document::text(unit,"kana");for(size_t i=0;i+2<reading.size();++i){auto a=static_cast<unsigned char>(reading[i]);if((a&0xf0)!=0xe0)continue;unsigned point=((a&15)<<12)|((static_cast<unsigned char>(reading[i+1])&63)<<6)|(static_cast<unsigned char>(reading[i+2])&63);if((point>=0x3041&&point<=0x3096)||(point>=0x30a1&&point<=0x30fa)||point==0x30fc)return true;}return false;
}
inline bool kanji(std::string const& value) {
    // Decode only enough UTF-8 to recognize CJK Unified Ideographs.
    for(size_t i=0;i+2<value.size();++i){auto a=static_cast<unsigned char>(value[i]);
        if((a&0xf0)==0xe0){auto b=static_cast<unsigned char>(value[i+1]),c=static_cast<unsigned char>(value[i+2]);
            unsigned point=((a&15)<<12)|((b&63)<<6)|(c&63);
            if(point>=0x3400&&point<=0x9fff)return true;
        }
    }return false;
}
inline std::vector<Issue> inspect(json::Array const& lines) {
    std::vector<Issue> issues;struct Interval {int start,end;std::string id;};std::vector<Interval> intervals;
    for(auto const& value:lines){auto const& line=static_cast<json::Object const&>(value);auto id=studio_document::text(line,"id");
        auto add=[&](std::string code,std::string message,bool error=false){issues.push_back({id,std::move(code),std::move(message),error});};
        try{studio_document::karaoke(value);}catch(std::exception const& error){add("invalid",error.what(),true);continue;}
        intervals.push_back({studio_document::time(line,"start"),studio_document::time(line,"end"),id});
        auto const& units=static_cast<json::Array const&>(line.at("units"));
        if(units.empty())add("timing","尚无逐音节时间");
        bool estimated=false,zero=false,missing=false;
        for(auto const& item:units){auto const& unit=static_cast<json::Object const&>(item);
            estimated|=studio_document::text(unit,"source")=="estimated";
            zero|=studio_document::time(unit,"start")==studio_document::time(unit,"end")&&!studio_document::text(unit,"text").empty();
            missing|=kanji(studio_document::text(unit,"text"))&&studio_document::text(unit,"kana").empty();
            auto parts=unit.find("highlights");if(parts!=unit.end())for(auto const& part:static_cast<json::Array const&>(parts->second)){
                auto const& object=static_cast<json::Object const&>(part);
                estimated|=studio_document::text(object,"source")=="estimated";
                zero|=studio_document::time(object,"start")==studio_document::time(object,"end");
            }
        }
        if(estimated)add("timing","仍含估算时间，请试听校准");
        if(zero)add("timing","存在零时长音节");
        if(missing||(units.empty()&&kanji(studio_document::text(line,"text"))&&studio_document::text(line,"kana").empty()))add("reading","汉字缺少假名读音");
        if(kanji(studio_document::text(line,"kana"))||std::any_of(units.begin(),units.end(),[](auto const& value){return kanji(studio_document::text(static_cast<json::Object const&>(value),"kana"));}))add("reading","假名字段中含有汉字，请结合转录复核实际唱法");
        auto match=line.find("match");if(match!=line.end()){auto const& info=static_cast<json::Object const&>(match->second);auto state=studio_document::text(info,"status");if(state=="uncertain"||state=="unmatched")add("match",state=="unmatched"?"没有足够转录对应，保留原时间，请人工定位":"歌词匹配存在歧义，请核对副歌位置或限定时间范围");}
        auto reviewed=line.find("reviewed");if(reviewed==line.end()||!static_cast<json::Boolean const&>(reviewed->second))add("review","尚未人工确认时间");
    }
    std::stable_sort(intervals.begin(),intervals.end(),[](auto const& a,auto const& b){return a.start<b.start;});
    int end=-1;for(auto const& interval:intervals){if(interval.start<end)issues.push_back({interval.id,"overlap","与前面的歌词重叠；合唱可保留，请试听确认",false});end=std::max(end,interval.end);}
    return issues;
}
inline json::Array lrc(std::string contents,int media_end=0) {
    if(contents.starts_with("\xEF\xBB\xBF"))contents.erase(0,3);
    static std::regex stamp(R"(\[(\d{1,4}):(\d{1,2})(?:[.:](\d{1,3}))?\])");
    static std::regex offset_tag(R"(\[offset:([+-]?\d+)\])",std::regex::icase);
    int64_t offset=0;
    for(auto it=std::sregex_iterator(contents.begin(),contents.end(),offset_tag);it!=std::sregex_iterator();++it)offset=std::stoll((*it)[1]);
    struct Entry {int64_t start;std::string text;};std::vector<Entry> entries;
    std::istringstream input(contents);std::string row;
    while(std::getline(input,row)){
        if(!row.empty()&&row.back()=='\r')row.pop_back();
        std::vector<int64_t> times;size_t tail=0;
        for(auto it=std::sregex_iterator(row.begin(),row.end(),stamp);it!=std::sregex_iterator();++it){
            int64_t minutes=std::stoll((*it)[1]),seconds=std::stoll((*it)[2]);auto fraction=(*it)[3].str();
            if(seconds>=60)throw std::runtime_error("LRC 秒数须小于 60");
            while(fraction.size()<3)fraction+='0';
            int64_t begin=minutes*60000+seconds*1000+std::stoi(fraction)+offset;
            if(begin<0||begin>2147470000)throw std::runtime_error("LRC 时间无效，或 offset 产生了负时间");
            times.push_back(begin);tail=it->position()+it->length();
        }
        if(times.empty()){
            if(std::regex_search(row,std::regex(R"(^\s*\[\d+:)")))throw std::runtime_error("LRC 时间标签格式无效");
            continue;
        }
        auto text=row.substr(tail);
        if(text.find('<')!=std::string::npos&&std::regex_search(text,std::regex(R"(<\d+:\d+)")))throw std::runtime_error("暂不支持带尖括号逐字时间的增强 LRC，请使用标准 LRC");
        for(auto time:times)entries.push_back({time,text});
        if(entries.size()>20000)throw std::runtime_error("LRC 行数过多");
    }
    std::stable_sort(entries.begin(),entries.end(),[](auto const& a,auto const& b){return a.start<b.start;});
    json::Array result;
    for(size_t i=0;i<entries.size();++i){auto const& entry=entries[i];if(entry.text.empty())continue;
        auto next=i+1;while(next<entries.size()&&entries[next].start<=entry.start)++next;
        int64_t end=next<entries.size()?entries[next].start:entry.start+5000;
        if(media_end>0){if(entry.start>=media_end)throw std::runtime_error("LRC 时间超出当前媒体长度");end=std::min(end,int64_t(media_end));}
        json::Object line;line["text"]=entry.text;line["start"]=entry.start;line["end"]=end;line["units"]=json::Array();line["reviewed"]=false;
        line["kana"]="";line["romaji"]="";line["translation"]="";line["locked"]=false;
        result.emplace_back(std::move(line));studio_document::karaoke(result.back());
    }
    if(result.empty())throw std::runtime_error("未找到有效歌词时间标签");return result;
}
}
