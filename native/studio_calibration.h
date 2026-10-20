// Copyright (c) 2026 Shengao Karaoke Studio contributors. MIT.
#pragma once
#include "studio_editing.h"

namespace studio_calibration {
inline void unit_time(json::Object& unit,int begin,int end) {
    int before=studio_document::time(unit,"start"),finish=studio_document::time(unit,"end");
    if(begin==before&&end==finish)return;
    if(end<=begin)throw std::runtime_error("每个词至少保留 10 ms；结束时间须晚于开始");
    auto parts=unit.find("highlights");
    if(parts!=unit.end()){
        auto& highlights=static_cast<json::Array&>(parts->second);bool fits=true,shift=end-begin==finish-before;
        for(size_t i=0;i<highlights.size();++i){auto const& part=static_cast<json::Object const&>(highlights[i]);int first=studio_document::time(part,"start"),last=studio_document::time(part,"end");if((i&&first<begin)||(i+1<highlights.size()&&last>end)||last<begin||first>end)fits=false;}
        for(size_t i=0;i<highlights.size();++i){auto& part=static_cast<json::Object&>(highlights[i]);int old_first=studio_document::time(part,"start"),old_last=studio_document::time(part,"end"),first=old_first,last=old_last;
            if(shift){first+=begin-before;last+=begin-before;}
            else if(fits){first=i==0&&first==before?begin:std::max(first,begin);last=i+1==highlights.size()&&last==finish?end:std::min(last,end);}
            else{auto moved=[&](int value){return std::clamp(begin+int(std::llround(double(value-before)*((end-begin)/10)/std::max(1,finish-before)))*10,begin,end);};first=moved(first);last=moved(last);}
            part["start"]=first;part["end"]=last;if(first!=old_first||last!=old_last)part["source"]=fits||shift?"manual":"estimated";
        }
    }
    unit["start"]=begin;unit["end"]=end;unit["source"]="manual";
}
inline json::UnknownElement timed(json::UnknownElement const& input,int target,int begin,int end) {
    if(begin<0||end<0||begin>2147480000||end>2147480000)throw std::runtime_error("时间超出范围");
    begin=(begin+5)/10*10;end=(end+5)/10*10;
    if(end<=begin)throw std::runtime_error("结束时间须晚于开始，最小时长为 10 ms");
    auto result=studio_workflow::copy(input);auto& row=static_cast<json::Object&>(result);auto& units=static_cast<json::Array&>(row.at("units"));
    if(target>=0){
        if(target>=int(units.size()))throw std::runtime_error("当前词已变化，请重新选择");
        auto& selected=static_cast<json::Object&>(units[target]);int old_begin=studio_document::time(selected,"start"),old_end=studio_document::time(selected,"end");
        if(target>0){auto& previous=static_cast<json::Object&>(units[target-1]);if(studio_document::time(previous,"end")==old_begin)unit_time(previous,studio_document::time(previous,"start"),begin);}
        if(target+1<int(units.size())){auto& next=static_cast<json::Object&>(units[target+1]);if(studio_document::time(next,"start")==old_end)unit_time(next,end,studio_document::time(next,"end"));}
        if(target==0&&(old_begin==studio_document::time(row,"start")||begin<studio_document::time(row,"start")))row["start"]=begin;
        if(target+1==int(units.size())&&(old_end==studio_document::time(row,"end")||end>studio_document::time(row,"end")))row["end"]=end;
        unit_time(selected,begin,end);
    }
    else{
        int old_start=studio_document::time(row,"start"),old_end=studio_document::time(row,"end");
        if(!units.empty()){
            auto& first=static_cast<json::Object&>(units.front());auto& last=static_cast<json::Object&>(units.back());
            int first_start=studio_document::time(first,"start"),last_end=studio_document::time(last,"end");
            if(units.size()==1)unit_time(first,(first_start==old_start||begin>first_start)?begin:first_start,(last_end==old_end||end<last_end)?end:last_end);
            else{
                if(first_start==old_start||begin>first_start)unit_time(first,begin,studio_document::time(first,"end"));
                if(last_end==old_end||end<last_end)unit_time(last,studio_document::time(last,"start"),end);
            }
        }
        row["start"]=begin;row["end"]=end;
    }
    studio_editing::manual(row);studio_document::karaoke(result);return result;
}
inline json::UnknownElement confirmed(json::UnknownElement const& input) {
    auto result=studio_workflow::copy(input);auto& row=static_cast<json::Object&>(result);
    for(auto& item:static_cast<json::Array&>(row.at("units"))){auto& unit=static_cast<json::Object&>(item);unit["source"]="manual";
        if(auto found=unit.find("highlights");found!=unit.end())for(auto& part:static_cast<json::Array&>(found->second))static_cast<json::Object&>(part)["source"]="manual";}
    studio_editing::manual(row);row["reviewed"]=true;studio_document::karaoke(result);return result;
}
}
