// Copyright (c) 2026 Shengao Karaoke Studio contributors. MIT.
#pragma once
#include <libaegisub/color.h>
#include <string_view>

// Recolour only unchanged upstream defaults; saved custom colours stay intact.
inline agi::Color StudioAudioColour(std::string_view name,agi::Color value) {
    struct Entry {std::string_view name;agi::Color before,after;};
    static Entry const entries[]={
        {"Colour/Audio Display/Keyframe",{255,0,255},{125,151,241}},
        {"Colour/Audio Display/Syllable Boundaries",{255,255,0},{112,218,199}},
        {"Colour/Audio Display/Line boundary Start",{216,0,0},{64,197,172}},
        {"Colour/Audio Display/Line boundary End",{0,0,216},{141,166,255}},
        {"Colour/Audio Display/Seconds Line",{0,100,255},{114,143,185}},
        {"Colour/Schemes/Icy Blue/UI/Selection",{65,34,103},{35,57,92}},
        {"Colour/Schemes/Icy Blue/UI Focused/Selection",{82,107,213},{61,89,216}},
        {"Colour/Schemes/Icy Blue/UI/Dark",{8,4,13},{20,29,46}},
        {"Colour/Schemes/Icy Blue/UI Focused/Dark",{8,4,13},{20,29,46}}
    };
    for(auto const& entry:entries)if(name==entry.name&&value==entry.before)return entry.after;
    return value;
}
