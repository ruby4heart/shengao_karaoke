// Copyright (c) 2026 Shengao Karaoke Studio contributors. MIT.
// Methods included by the original karaoke timing controller.
#include <algorithm>
bool AudioTimingControllerKaraoke::IsNearbyMarker(int ms,int sensitivity,bool alt) const {
    auto within=[&](int value){return std::abs(ms-value)<=sensitivity;};
    if(!alt && (within(start_marker)||within(end_marker)))return true;
    return std::any_of(markers.begin(),markers.end(),[&](auto const& marker){return within(marker);});
}

std::vector<AudioMarker*> AudioTimingControllerKaraoke::OnLeftClick(int ms,bool ctrl,bool alt,int sensitivity,int) {
    int nearest=sensitivity+1;KaraokeMarker *chosen=nullptr;
    for(auto& marker:markers){int distance=std::abs(ms-int(marker));if(distance<nearest){nearest=distance;chosen=&marker;}}
    // Prioritize an endpoint when an empty timing tag coincides with it. Alt
    // keeps the underlying syllable marker available for advanced editing.
    if(!alt){for(auto marker:{&start_marker,&end_marker}){int distance=std::abs(ms-int(*marker));if(distance<=nearest && distance<=sensitivity){nearest=distance;chosen=marker;}}}
    if(chosen && nearest<=sensitivity){
        if(chosen==&start_marker || chosen==&end_marker)return {chosen};
        size_t index=chosen-markers.data();
        return copy_ptrs<AudioMarker>(markers,index,ctrl?markers.size():index+1);
    }
    cur_syl=std::distance(markers.begin(),std::lower_bound(markers.begin(),markers.end(),ms));
    AnnounceUpdatedPrimaryRange();AnnounceUpdatedStyleRanges();return {};
}

int AudioTimingControllerKaraoke::MoveMarker(KaraokeMarker *marker,int position) {
    int rounded=int(std::clamp<int64_t>((int64_t(position)+5)/10*10,0,2147480000));
    if(marker==&start_marker || marker==&end_marker){
        int limit=marker==&start_marker?std::min(int(end_marker)-10,markers.empty()?int(end_marker)-10:int(markers.front())):
            std::max(int(start_marker)+10,markers.empty()?int(start_marker)+10:int(markers.back()));
        rounded=marker==&start_marker?std::min(rounded,limit):std::max(rounded,limit);
        if(rounded==int(*marker))return -1;
        marker->Move(rounded);kara->SetLineTimes(start_marker,end_marker);
        if(!labels.empty()){
            labels.front().range=TimeRange(start_marker,labels.front().range.end());
            labels.back().range=TimeRange(labels.back().range.begin(),end_marker);
        }
        return cur_syl;
    }
    if(markers.empty())return -1;
    int lower=marker==&markers.front()?int(start_marker):int(*(marker-1));
    int upper=marker==&markers.back()?int(end_marker):int(*(marker+1));
    rounded=std::clamp(rounded,lower,upper);
    if(rounded==int(*marker))return -1;
    marker->Move(rounded);size_t syllable=marker-markers.data()+1;
    kara->SetStartTime(syllable,rounded);
    labels[syllable-1].range=TimeRange(labels[syllable-1].range.begin(),rounded);
    labels[syllable].range=TimeRange(rounded,labels[syllable].range.end());
    return int(syllable);
}
