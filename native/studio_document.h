// Copyright (c) 2026 Shengao Karaoke Studio contributors. MIT.
#pragma once
#include <libaegisub/cajun/elements.h>
#include <stdexcept>
#include <string>
#include <cmath>

namespace studio_document {
inline std::string plain(std::string const& value) {
    std::string result;
    for(size_t i=0;i<value.size();++i) {
        if(value[i]=='\\' && i+1<value.size()) {
            char escape=value[i+1];
            if(escape=='N'||escape=='n'){result+='\n';++i;continue;}
            if(escape=='h'){result+="\xC2\xA0";++i;continue;}
        }
        result+=value[i];
    }
    return result;
}
inline std::string text(json::Object const& value, std::string const& key) {
    auto found=value.find(key);
    return found==value.end()?std::string():static_cast<json::String const&>(found->second);
}
inline int time(json::Object const& value, std::string const& key) {
    auto result=static_cast<json::Integer const&>(value.at(key));
    if(result<0||result>2147480000)throw std::runtime_error("时间超出支持范围");
    return static_cast<int>(result);
}
inline std::string literal(std::string const& value) {
    std::string result;
    for(char c:value) {
        if(c=='{')result+="｛";
        else if(c=='}')result+="｝";
        else if(c=='\\')result+="＼";
        else if(c=='\n')result+="\\N";
        else if(c!='\r'&&c!='\0')result+=c;
    }
    return result;
}

// Build and validate the entire line before the editor changes any document data.
inline std::string karaoke(json::UnknownElement const& value) {
    auto const& object=static_cast<json::Object const&>(value);
    int start=time(object,"start"),end=time(object,"end");
    auto original=text(object,"text");
    for(auto key:{"kana","romaji","translation"})text(object,key);
    for(auto key:{"locked","reviewed"}){
        auto flag=object.find(key);if(flag!=object.end())static_cast<json::Boolean const&>(flag->second);
    }
    auto match=object.find("match");
    if(match!=object.end()){
        auto const& info=static_cast<json::Object const&>(match->second);auto status=text(info,"status");
        if(!info.empty()&&status!="matched"&&status!="uncertain"&&status!="unmatched"&&status!="protected"&&status!="manual")throw std::runtime_error("匹配状态无效");
        for(auto key:{"score","coverage"}){auto found=info.find(key);if(found==info.end())continue;double number;
            try{number=static_cast<json::Double const&>(found->second);}catch(json::Exception const&){number=double(static_cast<json::Integer const&>(found->second));}
            if(!std::isfinite(number)||number<0||number>1)throw std::runtime_error("匹配相似度无效");
        }
        for(auto key:{"recognized","reason"})if(text(info,key).size()>400000)throw std::runtime_error("匹配说明过长");
    }
    if(end<=start||original.empty()||original.size()>80000)throw std::runtime_error("歌词内容或起止时间无效");
    auto const& units=static_cast<json::Array const&>(object.at("units"));
    if(units.size()>20000)throw std::runtime_error("音节数量过多");
    if(units.empty())return literal(original);
    std::string result,combined;
    int previous=start,cursor=(start+5)/10;
    for(auto const& value:units) {
        auto const& unit=static_cast<json::Object const&>(value);
        text(unit,"kana");text(unit,"romaji");
        int begin=time(unit,"start"),finish=time(unit,"end");
        if(begin<previous||finish<begin||finish>end)throw std::runtime_error("音节时间重叠或超出歌词范围");
        auto fragment=text(unit,"text");combined+=fragment;
        auto found=unit.find("highlights");
        if(found!=unit.end()&&!static_cast<json::Array const&>(found->second).empty()) {
            std::string reading;int index=0,part_previous=begin;
            for(auto const& value:static_cast<json::Array const&>(found->second)) {
                auto const& part=static_cast<json::Object const&>(value);
                int pbegin=time(part,"start"),pend=time(part,"end");
                auto kana=text(part,"kana");
                if(pbegin<part_previous||pend<pbegin||pend>finish||kana.empty())throw std::runtime_error("演唱音节时间或假名无效");
                int first=(pbegin+5)/10,last=(pend+5)/10;
                if(first>cursor)result+="{\\k"+std::to_string(first-cursor)+"}";
                result+="{\\kf"+std::to_string(last-first)+"}"+(index?"#|":literal(fragment)+"|!")+literal(kana);
                cursor=last;part_previous=pend;reading+=kana;++index;
            }
            if(reading!=text(unit,"kana"))throw std::runtime_error("演唱音节读音与词组假名不一致");
        } else {
            int first=(begin+5)/10,last=(finish+5)/10;
            if(first>cursor)result+="{\\k"+std::to_string(first-cursor)+"}";
            result+="{\\kf"+std::to_string(last-first)+"}"+literal(fragment);
            cursor=last;
        }
        previous=finish;
    }
    if(combined!=original)throw std::runtime_error("音节文字与原歌词不一致");
    return result;
}
}
