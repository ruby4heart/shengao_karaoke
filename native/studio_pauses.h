// Copyright (c) 2026 Shengao Karaoke Studio contributors. MIT.
#pragma once
#include "studio_editing.h"

namespace studio_pauses {
struct Leaf {int unit,part,start,end;std::string text;};
struct Gap {int start,end,left,right;};
inline std::vector<Leaf> leaves(json::UnknownElement const& input){
    std::vector<Leaf> out;auto const& line=static_cast<json::Object const&>(input);
    auto const& units=static_cast<json::Array const&>(line.at("units"));
    for(size_t i=0;i<units.size();++i){auto const& unit=static_cast<json::Object const&>(units[i]);auto found=unit.find("highlights");
        if(found!=unit.end()&&!static_cast<json::Array const&>(found->second).empty()){
            auto const& parts=static_cast<json::Array const&>(found->second);for(size_t j=0;j<parts.size();++j){auto const& part=static_cast<json::Object const&>(parts[j]);out.push_back({int(i),int(j),studio_document::time(part,"start"),studio_document::time(part,"end"),studio_document::text(part,"kana")});}
        }else out.push_back({int(i),-1,studio_document::time(unit,"start"),studio_document::time(unit,"end"),studio_document::text(unit,"text")});
    }return out;
}
inline std::vector<Gap> gaps(json::UnknownElement const& input,bool edges=false){
    studio_document::karaoke(input);auto spans=leaves(input);std::vector<Gap> out;if(spans.empty())return out;
    auto const& line=static_cast<json::Object const&>(input);int begin=studio_document::time(line,"start"),end=studio_document::time(line,"end");
    if(edges&&spans.front().start>begin)out.push_back({begin,spans.front().start,-1,0});
    for(size_t i=1;i<spans.size();++i)if(spans[i].start>spans[i-1].end)out.push_back({spans[i-1].end,spans[i].start,int(i-1),int(i)});
    if(edges&&spans.back().end<end)out.push_back({spans.back().end,end,int(spans.size()-1),-1});return out;
}
inline bool locked(json::UnknownElement const& input){
    auto flag=[](json::Object const& object){auto f=object.find("locked");return f!=object.end()&&static_cast<json::Boolean const&>(f->second);};
    auto const& line=static_cast<json::Object const&>(input);if(flag(line))return true;
    for(auto const& unit:static_cast<json::Array const&>(line.at("units")))if(flag(static_cast<json::Object const&>(unit)))return true;return false;
}
// 0 preserves exactly; 1 extends the previous syllable, 2 starts the next early.
inline json::UnknownElement apply(json::UnknownElement const& input,int mode,std::vector<int> const& selected,bool edges=false){
    if(mode<0||mode>2)throw std::runtime_error("请选择保留、并入前一音节或并入后一音节");
    auto all=gaps(input,edges);auto result=studio_workflow::copy(input);if(mode==0||selected.empty())return result;
    if(locked(input))throw std::runtime_error("该行或词已锁定，请先解除保护再人工处理停顿");
    auto refs=leaves(input);auto& line=static_cast<json::Object&>(result);auto& units=static_cast<json::Array&>(line.at("units"));
    auto change=[&](int index,char const* edge,int time){auto const& ref=refs[index];auto& unit=static_cast<json::Object&>(units[ref.unit]);
        if(ref.part>=0){auto& part=static_cast<json::Object&>(static_cast<json::Array&>(unit.at("highlights"))[ref.part]);part[edge]=time;part["source"]="manual";}
        else unit[edge]=time;unit["source"]="manual";
    };
    for(int index:selected){if(index<0||index>=int(all.size()))throw std::runtime_error("停顿列表已变化，请重新打开");auto const& gap=all[index];
        bool previous=(mode==1&&gap.left>=0)||gap.right<0;int target=previous?gap.left:gap.right;int edge=previous?gap.end:gap.start;
        change(target,previous?"end":"start",edge);
        if(gap.left<0||gap.right<0){static_cast<json::Object&>(units[refs[target].unit])[previous?"end":"start"]=edge;}
        else if(refs[gap.left].unit!=refs[gap.right].unit){
            auto& left=static_cast<json::Object&>(units[refs[gap.left].unit]);left["end"]=edge;left["source"]="manual";
            auto& right=static_cast<json::Object&>(units[refs[gap.right].unit]);right["start"]=edge;right["source"]="manual";
        }
    }
    studio_editing::manual(line);if(auto review=line.find("reading_review");review!=line.end())static_cast<json::Object&>(review->second)["stale"]=true;
    studio_document::karaoke(result);return result;
}
}
