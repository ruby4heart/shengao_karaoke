// Copyright (c) 2026 Shengao Karaoke Studio contributors. MIT.
#pragma once
#include <wx/control.h>
#include <wx/panel.h>
#include <wx/dcbuffer.h>
#include <wx/dcclient.h>
#include <wx/stattext.h>
#include <wx/sizer.h>
#include <wx/graphics.h>
#include <wx/tglbtn.h>
#include <wx/access.h>
#include <algorithm>
#include <cmath>
#ifdef _WIN32
#include <wx/msw/wrapwin.h>
#endif

namespace studio_ui {
inline wxColour const canvas(239,243,249),paper(255,255,255),ink(28,39,60),
    muted(91,105,128),line(210,219,233),soft(246,248,252),
    accent(61,89,216),tint(235,240,255),header(24,33,51),header_line(53,67,90);
inline wxFont font(double size=9.5,bool bold=false) {
    auto value=wxFont(wxFontInfo(size).FaceName(L"Microsoft YaHei UI"));
    if(bold)value.MakeBold();return value;
}
inline wxStaticText *label(wxWindow *parent,wxString const& text,double size=9.5,
                           wxColour colour=ink,bool bold=false) {
    auto value=new wxStaticText(parent,wxID_ANY,text);value->SetFont(font(size,bold));
    value->SetForegroundColour(colour);value->SetName(L"studio-label:"+text);return value;
}
inline wxPanel *rule(wxWindow *parent,wxColour colour=line) {
    auto value=new wxPanel(parent,wxID_ANY,wxDefaultPosition,parent->FromDIP(wxSize(0,1)),wxBORDER_NONE);
    value->SetName(L"studio-divider");value->SetBackgroundColour(colour);
    value->SetMinSize(parent->FromDIP(wxSize(0,1)));return value;
}
inline void field(wxWindow *value) {
    value->SetFont(font());value->SetForegroundColour(ink);value->SetBackgroundColour(paper);
}
inline wxString ellipsized(wxDC& dc,wxString text,int width) {
    text.Replace(L"\n",L" / ");
    if(dc.GetTextExtent(text).x<=width)return text;
    while(!text.empty()&&dc.GetTextExtent(text+L"…").x>width)text.RemoveLast();
    return text+L"…";
}
}

class StudioSurface : public wxPanel {
public:
    StudioSurface(wxWindow *parent,wxWindowID id=wxID_ANY,wxSize size=wxDefaultSize)
    :wxPanel(parent,id,wxDefaultPosition,size,wxTAB_TRAVERSAL|wxCLIP_CHILDREN|wxBORDER_NONE) {
        SetBackgroundColour(studio_ui::paper);SetForegroundColour(studio_ui::ink);SetFont(studio_ui::font());
        SetName(L"studio-surface");SetBackgroundStyle(wxBG_STYLE_PAINT);
        Bind(wxEVT_PAINT,[this](wxPaintEvent&){wxAutoBufferedPaintDC dc(this);Paint(dc);});
        Bind(wxEVT_SIZE,[this](wxSizeEvent& e){Refresh(false);e.Skip();});
    }
    void Border(wxDC& dc) const {
        auto size=GetClientSize();if(size.x<2||size.y<2)return;
        dc.SetPen(wxPen(studio_ui::line));dc.SetBrush(*wxTRANSPARENT_BRUSH);
        dc.DrawRoundedRectangle(0,0,size.x-1,size.y-1,FromDIP(10));
    }
    void Paint(wxDC& dc) const {
        dc.SetBackground(wxBrush(GetParent()?GetParent()->GetBackgroundColour():studio_ui::canvas));dc.Clear();
        auto size=GetClientSize();dc.SetPen(wxPen(studio_ui::line));dc.SetBrush(wxBrush(GetBackgroundColour()));
        if(size.x>1&&size.y>1)dc.DrawRoundedRectangle(0,0,size.x-1,size.y-1,FromDIP(10));
    }
};

class StudioButton : public wxControl {
public:
    enum class Kind { Primary,Secondary,Quiet,Dark,DarkPrimary,Tab };
    struct Colours {wxColour background,foreground,border;};
private:
    Kind kind;
    bool toggle=false,value=false,hover=false,pressed=false;
    void Activate() {
        if(!IsEnabled())return;
        if(toggle)value=!value;Refresh(false);
        wxCommandEvent event(toggle?wxEVT_TOGGLEBUTTON:wxEVT_BUTTON,GetId());
        event.SetEventObject(this);event.SetInt(value);ProcessWindowEvent(event);
    }
public:
    StudioButton(wxWindow *parent,wxString const& text,Kind style=Kind::Secondary,
                 wxSize size=wxSize(-1,36),bool toggles=false)
    :wxControl(parent,wxID_ANY,wxDefaultPosition,parent->FromDIP(size),wxBORDER_NONE|wxWANTS_CHARS),
     kind(style),toggle(toggles) {
        wxControl::SetLabel(text);SetName(text);SetToolTip(text);SetFont(studio_ui::font(9.5,style==Kind::Primary||style==Kind::DarkPrimary));
        SetBackgroundStyle(wxBG_STYLE_PAINT);SetMinSize(parent->FromDIP(wxSize(std::max(0,size.x),size.y)));
        SetCursor(wxCursor(wxCURSOR_HAND));
        Bind(wxEVT_PAINT,[this](wxPaintEvent&){wxAutoBufferedPaintDC dc(this);Render(dc,GetClientSize());});
        Bind(wxEVT_ENTER_WINDOW,[this](wxMouseEvent& e){hover=true;Refresh(false);e.Skip();});
        Bind(wxEVT_LEAVE_WINDOW,[this](wxMouseEvent& e){hover=false;Refresh(false);e.Skip();});
        Bind(wxEVT_LEFT_DOWN,[this](wxMouseEvent&){if(!IsEnabled())return;SetFocus();pressed=true;if(!HasCapture())CaptureMouse();Refresh(false);});
        Bind(wxEVT_LEFT_UP,[this](wxMouseEvent& e){bool click=pressed&&GetClientRect().Contains(e.GetPosition());pressed=false;if(HasCapture())ReleaseMouse();Refresh(false);if(click)Activate();});
        Bind(wxEVT_MOUSE_CAPTURE_LOST,[this](wxMouseCaptureLostEvent&){pressed=false;Refresh(false);});
        Bind(wxEVT_KEY_DOWN,[this](wxKeyEvent& e){if(e.GetKeyCode()==WXK_SPACE||e.GetKeyCode()==WXK_RETURN||e.GetKeyCode()==WXK_NUMPAD_ENTER){pressed=true;Refresh(false);}else e.Skip();});
        Bind(wxEVT_KEY_UP,[this](wxKeyEvent& e){if((e.GetKeyCode()==WXK_SPACE||e.GetKeyCode()==WXK_RETURN||e.GetKeyCode()==WXK_NUMPAD_ENTER)&&pressed){pressed=false;Activate();}else e.Skip();});
        Bind(wxEVT_SET_FOCUS,[this](wxFocusEvent& e){Refresh(false);e.Skip();});
        Bind(wxEVT_KILL_FOCUS,[this](wxFocusEvent& e){pressed=false;Refresh(false);e.Skip();});
        Bind(wxEVT_SIZE,[this](wxSizeEvent& e){Refresh(false);e.Skip();});
    }
    bool Enable(bool enabled=true) override {bool result=wxControl::Enable(enabled);pressed=false;Refresh(false);return result;}
    void SetLabel(wxString const& text) override {wxControl::SetLabel(text);SetName(text);SetToolTip(text);InvalidateBestSize();Refresh(false);}
    void SetValue(bool state) {value=state;Refresh(false);}
    bool GetValue() const {return value;}
    void Click() {Activate();}
    Kind GetKind() const {return kind;}
    Colours Palette(bool enabled) const {
        using namespace studio_ui;
        if(kind==Kind::Dark||kind==Kind::DarkPrimary){
            if(!enabled)return {wxColour(31,42,62),wxColour(153,168,192),wxColour(45,60,82)};
            if(kind==Kind::DarkPrimary)return {pressed?wxColour(43,68,177):hover?wxColour(78,106,233):accent,*wxWHITE,accent};
            return {pressed?wxColour(48,64,90):hover?wxColour(44,57,80):wxColour(31,43,63),wxColour(229,235,246),wxColour(53,68,93)};
        }
        if(!enabled)return {wxColour(237,241,247),wxColour(88,102,124),wxColour(219,226,237)};
        if(kind==Kind::Primary)return {pressed?wxColour(43,68,177):hover?wxColour(78,106,233):accent,*wxWHITE,accent};
        if(kind==Kind::Tab)return {value?tint:hover?soft:paper,value?accent:muted,value?wxColour(200,212,252):paper};
        if(kind==Kind::Quiet)return {hover||pressed?tint:paper,hover?accent:ink,hover?tint:paper};
        return {pressed?tint:hover?soft:paper,ink,hover?wxColour(170,187,226):line};
    }
    wxRect CaptionBounds(wxDC& dc,wxSize size,double scale=1) const {
        auto text_font=GetFont();text_font.SetFractionalPointSize(text_font.GetFractionalPointSize()*scale);dc.SetFont(text_font);
        auto extent=dc.GetTextExtent(GetLabel());return wxRect((size.x-extent.x)/2,(size.y-extent.y)/2,extent.x,extent.y);
    }
    void Render(wxDC& dc,wxSize size,double scale=1) const {
        auto colours=Palette(IsEnabled());
        dc.SetBackground(wxBrush(GetParent()?GetParent()->GetBackgroundColour():studio_ui::paper));dc.Clear();
        dc.SetPen(wxPen(colours.border));dc.SetBrush(wxBrush(colours.background));
        dc.DrawRoundedRectangle(0,0,std::max(0,size.x-1),std::max(0,size.y-1),FromDIP(6)*scale);
        auto bounds=CaptionBounds(dc,size,scale);auto text=GetLabel();
        int inset=std::max(4,int(FromDIP(12)*scale));
        if(bounds.width>size.x-2*inset)text=studio_ui::ellipsized(dc,text,std::max(0,size.x-2*inset));
        auto extent=dc.GetTextExtent(text);dc.SetTextForeground(colours.foreground);dc.DrawText(text,(size.x-extent.x)/2,(size.y-extent.y)/2);
        if(kind==Kind::Tab&&value){dc.SetPen(*wxTRANSPARENT_PEN);dc.SetBrush(wxBrush(studio_ui::accent));dc.DrawRoundedRectangle(inset,size.y-int(FromDIP(3)*scale),std::max(0,size.x-2*inset),std::max(1,int(FromDIP(3)*scale)),1);}
        if(HasFocus()&&IsEnabled()){dc.SetPen(wxPen(kind==Kind::Dark?wxColour(166,187,255):wxColour(146,166,240),std::max(1,int(scale))));dc.SetBrush(*wxTRANSPARENT_BRUSH);int margin=std::max(2,int(3*scale));dc.DrawRoundedRectangle(margin,margin,std::max(0,size.x-2*margin-1),std::max(0,size.y-2*margin-1),FromDIP(4)*scale);}
    }
protected:
#if wxUSE_ACCESSIBILITY
    wxAccessible *CreateAccessible() override;
#endif
    wxSize DoGetBestClientSize() const override {
        auto extent=GetTextExtent(GetLabel());return wxSize(extent.x+FromDIP(28),std::max(FromDIP(36),extent.y+FromDIP(14)));
    }
};

#if wxUSE_ACCESSIBILITY
class StudioButtonAccessible final : public wxAccessible {
    StudioButton *button;
public:
    explicit StudioButtonAccessible(StudioButton *value):wxAccessible(value),button(value){}
    wxAccStatus GetName(int child,wxString *name) override {if(child!=0)return wxACC_NOT_IMPLEMENTED;*name=button->GetLabel();return wxACC_OK;}
    wxAccStatus GetRole(int child,wxAccRole *role) override {if(child!=0)return wxACC_NOT_IMPLEMENTED;*role=button->GetKind()==StudioButton::Kind::Tab?wxROLE_SYSTEM_PAGETAB:wxROLE_SYSTEM_PUSHBUTTON;return wxACC_OK;}
    wxAccStatus GetState(int child,long *state) override {
        if(child!=0)return wxACC_NOT_IMPLEMENTED;*state=wxACC_STATE_SYSTEM_FOCUSABLE;
        if(!button->IsEnabled())*state|=wxACC_STATE_SYSTEM_UNAVAILABLE;
        if(button->HasFocus())*state|=wxACC_STATE_SYSTEM_FOCUSED;
        if(button->GetValue())*state|=wxACC_STATE_SYSTEM_SELECTED;return wxACC_OK;
    }
    wxAccStatus GetDefaultAction(int child,wxString *action) override {if(child!=0)return wxACC_NOT_IMPLEMENTED;*action=L"按下";return wxACC_OK;}
    wxAccStatus DoDefaultAction(int child) override {if(child!=0)return wxACC_NOT_IMPLEMENTED;if(!button->IsEnabled())return wxACC_FAIL;button->Click();return wxACC_OK;}
};
inline wxAccessible *StudioButton::CreateAccessible(){return new StudioButtonAccessible(this);}
#endif

namespace studio_ui {
// Draw the same custom widgets into a capture of this app, using real geometry.
// Native editors and media are rendered separately by their own print/render APIs.
inline void render_widgets(wxWindow *window,wxWindow *root,wxMemoryDC& output) {
    if(!window->IsShown())return;
    auto origin=root->ScreenToClient(window->ClientToScreen(wxPoint(0,0)));
    auto size=window->GetClientSize();
    wxRect visible(origin,size);
    for(auto parent=window->GetParent();parent;parent=parent->GetParent()){
        if(!parent->IsShown()){visible=wxRect();break;}
        visible.Intersect(wxRect(root->ScreenToClient(parent->ClientToScreen(wxPoint(0,0))),parent->GetClientSize()));
        if(parent==root)break;
    }
    if(visible.IsEmpty())return;
    if(auto surface=dynamic_cast<StudioSurface*>(window)){
        if(size.x>0&&size.y>0){
            wxBitmap bitmap(size.x,size.y);
            {wxMemoryDC dc(bitmap);surface->Paint(dc);
#ifdef _WIN32
                auto hdc=static_cast<HDC>(dc.GetHDC());auto saved=::SaveDC(hdc);
                ::SendMessageW(static_cast<HWND>(surface->GetHandle()),WM_PRINT,reinterpret_cast<WPARAM>(hdc),PRF_CLIENT|PRF_CHILDREN|PRF_ERASEBKGND);
                ::RestoreDC(hdc,saved);
#endif
                surface->Border(dc);
            }
            output.SetClippingRegion(visible);output.DrawBitmap(bitmap,origin);output.DestroyClippingRegion();
        }
    }
    if(auto button=dynamic_cast<StudioButton*>(window)){
        if(size.x>0&&size.y>0){wxBitmap bitmap(size.x,size.y);{wxMemoryDC dc(bitmap);button->Render(dc,size);}output.SetClippingRegion(visible);output.DrawBitmap(bitmap,origin);output.DestroyClippingRegion();}
    }
    for(auto child:window->GetChildren())render_widgets(child,root,output);
}
}
