// Copyright (c) 2026 Shengao Karaoke Studio contributors. MIT.
#pragma once
#include <libaegisub/signal.h>
#include <wx/panel.h>
#include <wx/vlbox.h>
#include "studio_theme.h"
#include <vector>
namespace agi { struct Context; }
class AssDialogue;
class wxStaticText;
class wxTextCtrl;
class wxChoice;
class wxButton;

class StudioLyrics final : public wxVListBox, private agi::signal::ConnectionScope {
    struct Card {int id,row;wxString text,reading,time,badge;bool locked,reviewed,uncertain;};
    agi::Context *context;
    std::vector<Card> cards;
    wxString query;
    int filter=0;
    bool syncing=false;
    wxStaticText *empty_hint=nullptr;
    void OnDrawItem(wxDC& dc,wxRect const& rect,size_t index) const override;
    void OnDrawBackground(wxDC& dc,wxRect const& rect,size_t index) const override;
    wxCoord OnMeasureItem(size_t index) const override;
    void ApplySelection(int index);
public:
    StudioLyrics(wxWindow *parent,agi::Context *context);
    void Rebuild();
    void SyncSelection();
    void SetFilter(wxString const& text,int kind);
    void Choose(int index,bool extend=false);
    int IdAt(size_t index) const;
    void RenderCards(wxDC& dc) const;
};

class StudioShell final : public wxPanel, private agi::signal::ConnectionScope {
    agi::Context *context;
    wxPanel *body;
    wxWindow *advanced=nullptr,*editing=nullptr;
    wxWindow *transport=nullptr;
    wxStaticText *project_label,*current_text=nullptr,*current_time=nullptr,*count_label=nullptr;
    wxStaticText *playback_time=nullptr;
    wxStaticText *guide_hint=nullptr;
    StudioButton *next_step=nullptr;
    StudioButton *undo,*redo,*maximize;
    wxChoice *filter=nullptr;
    wxChoice *layout_mode=nullptr;
    wxTextCtrl *search=nullptr;
    bool fitting=false;
    void Tools();
public:
    StudioLyrics *lyrics=nullptr;
    StudioShell(wxWindow *parent,agi::Context *context);
    wxPanel *Body() const { return body; }
    void Attach(wxWindow *lyrics_parent,wxWindow *editing_parent,wxWindow *advanced_editor);
    void UpdateState();
    void ToggleMaximize();
    void ToggleAdvanced();
    void FitVideo();
    void SetView(int mode);
    wxPanel *Transport(wxWindow *parent);
    bool CurrentEditorFits() const;
    bool TransportFits() const;
};
