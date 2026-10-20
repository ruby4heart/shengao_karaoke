// Copyright (c) 2026 Shengao Karaoke Studio contributors. MIT.
#pragma once
#include <libaegisub/ass/karaoke.h>
#include <algorithm>
#include <string_view>
#include <vector>

namespace studio_karaoke {
// Silence is timing data, not a word. Keep it in the ASS model, but attach its
// display area to the preceding word (or the following word at the line start).
inline bool blank(std::string_view text) {
    while (!text.empty()) {
        bool consumed=false;
        for (std::string_view space : {" ","\t","\r","\n","\v","\f","\xC2\x85","\xC2\xA0",
                "\xE1\x9A\x80","\xE2\x80\x80","\xE2\x80\x81","\xE2\x80\x82","\xE2\x80\x83",
                "\xE2\x80\x84","\xE2\x80\x85","\xE2\x80\x86","\xE2\x80\x87","\xE2\x80\x88",
                "\xE2\x80\x89","\xE2\x80\x8A","\xE2\x80\x8B","\xE2\x80\xA8","\xE2\x80\xA9",
                "\xE2\x80\xAF","\xE2\x81\x9F","\xE3\x80\x80","\xEF\xBB\xBF","\\h","\\N","\\n"}) {
            if (text.starts_with(space)) {text.remove_prefix(space.size());consumed=true;break;}
        }
        if (!consumed) return false;
    }
    return true;
}

inline std::vector<size_t> visible_syllables(agi::ass::Karaoke const& karaoke) {
    std::vector<size_t> result;
    size_t index=0;
    for (auto const& syllable:karaoke) {
        if (!blank(syllable.text)) result.push_back(index);
        ++index;
    }
    return result;
}

inline bool can_split(std::string_view text,size_t byte) {
    if(text.find('|')!=std::string_view::npos)return false;
    return byte>0 && byte<text.size() && (static_cast<unsigned char>(text[byte])&0xC0)!=0x80
        && !blank(text.substr(0,byte)) && !blank(text.substr(byte));
}

// A displayed boundary can span several empty \k tags. One click joins the
// actual words and all intervening pauses; total time, text and tags survive.
inline bool remove_boundary(agi::ass::Karaoke& karaoke,std::vector<size_t> const& visible,size_t boundary) {
    if (!boundary || boundary>=visible.size()) return false;
    if(std::any_of(karaoke.begin(),karaoke.end(),[](auto const& unit){return unit.text.find('|')!=std::string::npos;}))return false;
    size_t first=visible[boundary-1],last=visible[boundary];
    if (first>=last || last>=karaoke.size()) return false;
    std::vector<agi::ass::KaraokeSyllable> syllables(karaoke.begin(),karaoke.end());
    auto& joined=syllables[first];
    for (size_t index=first+1;index<=last;++index) {
        auto const& next=syllables[index];
        joined.duration+=next.duration;
        // Several empty timing tags can put different style tags at the same
        // text offset. Append them in order rather than overwriting each other.
        for (auto const& [offset,tags]:next.ovr_tags) joined.ovr_tags[joined.text.size()+offset]+=tags;
        joined.text+=next.text;
    }
    syllables.erase(syllables.begin()+first+1,syllables.begin()+last+1);
    karaoke.SetLine(std::move(syllables),false,std::nullopt);
    return true;
}

inline std::string_view base_text(std::string const& text){
    std::string_view value(text);value=value.substr(0,value.find('|'));
    return value=="#"||value=="＃"?std::string_view():value;
}
inline std::string display_text(std::string const& text){
    auto pipe=text.find('|');if(pipe==std::string::npos)return text;
    auto base=base_text(text);auto reading=text.substr(pipe+1);if(reading.starts_with('!'))reading.erase(0,1);
    return base.empty()?reading:std::string(base)+"〔"+reading+"〕";
}
inline void preserve_tags(std::vector<agi::ass::KaraokeSyllable> const& before,std::vector<agi::ass::KaraokeSyllable>& after){
    std::string old_text,new_text;for(auto const& syllable:before)old_text+=base_text(syllable.text);for(auto const& syllable:after)new_text+=base_text(syllable.text);
    if(old_text!=new_text||after.empty())return;
    std::vector<std::pair<size_t,std::string>> tags;size_t offset=0;
    for(auto const& syllable:before){auto base=base_text(syllable.text);for(auto const& [position,value]:syllable.ovr_tags)tags.emplace_back(offset+std::min(position,base.size()),value);offset+=base.size();}
    for(auto const& [position,value]:tags){size_t start=0;
        for(size_t i=0;i<after.size();++i){auto& syllable=after[i];size_t end=start+base_text(syllable.text).size();
            if(position<end||i+1==after.size()){syllable.ovr_tags[std::min(position-start,base_text(syllable.text).size())]+=value;break;}start=end;}
    }
}
}
