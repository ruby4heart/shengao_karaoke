// Copyright (c) 2026 Shengao Karaoke Studio contributors. MIT.
// Included in audio_karaoke.cpp; the upstream timing model is left intact.
void AudioKaraoke::SetDisplayText() {
    wxMemoryDC dc;
    dc.SetFont(split_font);
    auto get_char_width=[&](std::string_view character) -> int {
        if (auto it=char_widths.find(character);it!=char_widths.end()) return it->second;
        auto size=dc.GetTextExtent(to_wx(character));
        char_height=std::max(char_height,size.GetHeight());
        char_widths.emplace(character,size.GetWidth());
        return size.GetWidth();
    };
    char_width=std::max(1,get_char_width(" "));
    std::vector<int> widths;
    spaced_text.clear();char_to_byte.clear();studio_char_syllables.clear();syl_start_points.clear();
    studio_char_edges.clear();studio_text_width=0;
    studio_syl_indices=studio_karaoke::visible_syllables(*kara);
    studio_furigana=std::any_of(kara->begin(),kara->end(),[](auto const& unit){return unit.text.find('|')!=std::string::npos;});
    split_area->SetToolTip(studio_furigana?L"点击选中音节，双击试听。修改注音音节请用注音页的 | 分音，避免拆坏汉字与读音对应。":L"点击词内添加分界，点击分界合并；对号提交，叉号取消。原词空格保持不变。");
    for (size_t group=0;group<studio_syl_indices.size();++group) {
        syl_start_points.push_back(spaced_text.size());
        size_t first=group?studio_syl_indices[group]:0;
        size_t last=group+1<studio_syl_indices.size()?studio_syl_indices[group+1]:kara->size();
        for (size_t index=first;index<last;++index) {
            size_t byte=0;
            agi::BreakIterator characters;
            auto displayed=studio_karaoke::display_text((kara->begin()+index)->text);characters.set_text(displayed);
            for (;!characters.done();characters.next()) {
                auto character=characters.current();
                int width=get_char_width(character);char_width=std::max(char_width,width);
                widths.push_back(width);spaced_text.emplace_back(to_wx(character));
                char_to_byte.push_back(byte);studio_char_syllables.push_back(index);
                byte+=character.size();
            }
        }
    }
    if(!studio_syl_indices.empty()){
        auto anchor=studio_syl_indices.back();
        char_to_byte.push_back((kara->begin()+anchor)->text.size());studio_char_syllables.push_back(anchor);
    }
    char_x.resize(widths.size());
    for(size_t i=0;i<widths.size();++i){studio_char_edges.push_back(studio_text_width);char_x[i]=studio_text_width;studio_text_width+=widths[i];}
    studio_char_edges.push_back(studio_text_width);
    syl_lines.clear();
    for (size_t i=1;i<syl_start_points.size();++i)
        syl_lines.push_back(studio_char_edges[syl_start_points[i]]);
    // Changing words, deleting a boundary, or resizing must not leave scrolling
    // beyond the last visible word or a stale hover line in a newly empty strip.
    scroll_x=std::clamp(scroll_x,0,std::max(0,studio_text_width+5-split_area->GetClientSize().x));
    mouse_pos=-1;
    RenderText();
}

void AudioKaraoke::OnMouse(wxMouseEvent &event) {
    if (!enabled) return;
    mouse_pos=event.GetX();
    if (event.Leaving()) {mouse_pos=-1;split_area->Refresh(false);return;}
    if (scroll_timer.IsRunning() || split_area->HasCapture()) {
        if (event.LeftUp()) {scroll_timer.Stop();split_area->ReleaseMouse();}
        return;
    }
    int width=split_area->GetClientSize().x;
    scroll_dir=scroll_x>0 && mouse_pos<20 ? -1 :
        scroll_x+width<rendered_line.GetWidth() && mouse_pos>width-20 ? 1 : 0;
    if (scroll_dir) {
        mouse_pos=-1;
        if (event.LeftDown()) {split_area->Refresh(false);scroll_timer.Start(50);split_area->CaptureMouse();OnScrollTimer();}
        return;
    }
    if (syl_start_points.empty()) {mouse_pos=-1;split_area->Refresh(false);return;}
    int shifted=std::max(0,mouse_pos+scroll_x);
    auto edge=std::lower_bound(studio_char_edges.begin(),studio_char_edges.end(),shifted);
    int split_pos=int(edge-studio_char_edges.begin());
    if(edge==studio_char_edges.end())split_pos=int(spaced_text.size());
    else if(split_pos>0 && shifted-studio_char_edges[split_pos-1]<*edge-shifted)--split_pos;
    int group=last_lt_or_eq(syl_start_points,split_pos);
    if(studio_furigana){
        mouse_pos=-1;
        if(event.LeftDown()||event.LeftDClick()){
            auto const& unit=*(kara->begin()+studio_syl_indices[group]);auto timing=c->audioController->GetTimingController();
            if(timing)timing->OnLeftClick(unit.start_time+unit.duration/2,false,false,0,0);
            if(event.LeftDClick())c->audioController->PlayPrimaryRange();
        }
        split_area->Refresh(false);return;
    }
    bool right=group>0 && std::abs(shifted-syl_lines[group-1])<=FromDIP(3);
    bool left=group<int(syl_lines.size()) && std::abs(shifted-syl_lines[group])<=FromDIP(3);
    click_will_remove_split=left || right;
    size_t target=studio_char_syllables[split_pos],byte=char_to_byte[split_pos];
    bool can_add=studio_karaoke::can_split((kara->begin()+target)->text,byte);
    int boundary=group+(left && !right);
    if (click_will_remove_split) mouse_pos=syl_lines[boundary-1]-scroll_x;
    else if (!can_add) mouse_pos=-1;
    if (!event.LeftDown()) {split_area->Refresh(false);return;}
    if (click_will_remove_split) studio_karaoke::remove_boundary(*kara,studio_syl_indices,boundary);
    else if (can_add) kara->AddSplit(target,byte);
    else return;
    SetDisplayText();accept_button->Enable(true);cancel_button->Enable(true);split_area->Refresh(false);
}
