// Copyright (c) 2026 Shengao Karaoke Studio contributors. MIT.
void FrameMain::InitContents() {
    // Shengao three-pane workspace, with independent chrome and lyric cards.
    auto shell = new StudioShell(this,context.get());context->studioShell=shell;
    auto Panel = shell->Body();
    auto split = new wxSplitterWindow(Panel, wxID_ANY, wxDefaultPosition, wxDefaultSize, wxSP_LIVE_UPDATE|wxBORDER_NONE);
    auto lyrics = new StudioSurface(split);
    auto center = new StudioSurface(split);
    auto editing = new wxScrolledWindow(center,wxID_ANY,wxDefaultPosition,wxDefaultSize,wxVSCROLL|wxHSCROLL|wxTAB_TRAVERSAL|wxBORDER_NONE);editing->SetScrollRate(12,12);
    lyrics->SetBackgroundColour(studio_ui::paper);editing->SetBackgroundColour(studio_ui::paper);editing->SetFont(studio_ui::font());
    auto center_layout=new wxBoxSizer(wxVERTICAL);center_layout->Add(editing,1,wxEXPAND|wxALL,14);center->SetSizer(center_layout);
    auto columns=OPT_GET("Subtitle/Grid/Column")->GetListBool();
    if(columns.size()==1 && columns.front())
        OPT_SET("Subtitle/Grid/Column")->SetListBool({true,false,true,true,false,false,false,false,false,false,false,true});
    context->subsGrid = new BaseGrid(lyrics, context.get());
    context->subsGrid->Hide();
    videoBox = new VideoBox(editing, false, context.get());
    videoBox->SetMinSize(wxSize(0,-1));
    context->audioBox = audioBox = new AudioBox(editing, context.get());
    auto EditBox = new SubsEditBox(editing, context.get());EditBox->Hide();
    ToolsSizer = new wxBoxSizer(wxVERTICAL);
    ToolsSizer->Add(audioBox, 0, wxEXPAND);
    TopSizer = new wxBoxSizer(wxVERTICAL);
    TopSizer->Add(videoBox, 0, wxEXPAND);
    TopSizer->Add(studio_ui::rule(editing),0,wxEXPAND|wxTOP|wxBOTTOM,12);
    auto audio_title=studio_ui::label(editing,L"音频时间轴",10,studio_ui::ink,true);TopSizer->Add(audio_title,0,wxBOTTOM,8);
    TopSizer->Add(ToolsSizer, 0, wxEXPAND);
    MainSizer = new wxBoxSizer(wxVERTICAL);
    auto heading=new wxBoxSizer(wxHORIZONTAL);auto title=studio_ui::label(editing,L"预览与校准",12,studio_ui::ink,true);heading->Add(title,1,wxALIGN_CENTER_VERTICAL);
    auto media=new StudioButton(editing,L"＋ 添加媒体",StudioButton::Kind::Secondary,wxSize(108,32));media->Bind(wxEVT_BUTTON,[this](wxCommandEvent&){context->studioPanel->AddMedia();});heading->Add(media,0);
    MainSizer->Add(heading,0,wxEXPAND|wxBOTTOM,12);
    MainSizer->Add(TopSizer, 0, wxEXPAND);
    MainSizer->Add(shell->Transport(editing),0,wxEXPAND|wxTOP,10);
    MainSizer->AddStretchSpacer();
    editing->SetSizer(MainSizer);
    split->SetMinimumPaneSize(250);
    split->SplitVertically(lyrics, center, FromDIP(300));
    split->SetSashGravity(0.0);
    CallAfter([this,split]{split->SetSashPosition(FromDIP(300));split->SetSashGravity(.24);});
    context->studioPanel = studioPanel = new StudioPanel(Panel, context.get());
    shell->Attach(lyrics,editing,EditBox);
    auto workspace = new wxBoxSizer(wxHORIZONTAL);
    workspace->Add(split, 1, wxEXPAND);
    workspace->Add(studioPanel, 0, wxEXPAND | wxLEFT, 14);
    auto padded=new wxBoxSizer(wxVERTICAL);padded->Add(workspace,1,wxEXPAND|wxALL,14);Panel->SetSizer(padded);
    Layout();
#ifdef __WXMSW__
#pragma comment(lib,"dwmapi.lib")
    // Recalculate the native frame after replacing the system caption.
    auto hwnd=static_cast<HWND>(GetHandle());
    BOOL dark=TRUE;COLORREF border=RGB(24,33,51);
    ::DwmSetWindowAttribute(hwnd,20,&dark,sizeof(dark));
    ::DwmSetWindowAttribute(hwnd,34,&border,sizeof(border));
    MARGINS margins{1,1,1,1};::DwmExtendFrameIntoClientArea(hwnd,&margins);
    ::SetWindowPos(hwnd,nullptr,0,0,0,0,SWP_NOMOVE|SWP_NOSIZE|SWP_NOZORDER|SWP_NOACTIVATE|SWP_FRAMECHANGED);
#endif
}

#ifdef __WXMSW__
WXLRESULT FrameMain::MSWWindowProc(WXUINT message,WXWPARAM wParam,WXLPARAM lParam) {
    auto hwnd=static_cast<HWND>(GetHandle());
    if(message==WM_WINDOWPOSCHANGING&&lParam&&::IsZoomed(hwnd)&&!IsFullScreen()){
        auto result=wxFrame::MSWWindowProc(message,wParam,lParam);
        auto position=reinterpret_cast<WINDOWPOS*>(lParam);MONITORINFO monitor{sizeof(MONITORINFO)};
        if((position->flags&(SWP_NOMOVE|SWP_NOSIZE))==(SWP_NOMOVE|SWP_NOSIZE))return result;
        RECT target{};::GetWindowRect(hwnd,&target);
        int width=position->flags&SWP_NOSIZE?target.right-target.left:position->cx,height=position->flags&SWP_NOSIZE?target.bottom-target.top:position->cy;
        if(!(position->flags&SWP_NOMOVE)){target.left=position->x;target.top=position->y;}target.right=target.left+width;target.bottom=target.top+height;
        if(::GetMonitorInfoW(::MonitorFromRect(&target,MONITOR_DEFAULTTONEAREST),&monitor)){
            position->x=monitor.rcWork.left;position->y=monitor.rcWork.top;
            position->cx=monitor.rcWork.right-monitor.rcWork.left;position->cy=monitor.rcWork.bottom-monitor.rcWork.top;
            position->flags&=~(SWP_NOMOVE|SWP_NOSIZE);
        }
        return result;
    }
    if(message==WM_GETMINMAXINFO&&lParam){
        wxFrame::MSWWindowProc(message,wParam,lParam);
        MONITORINFO monitor{sizeof(MONITORINFO)};
        if(::GetMonitorInfoW(::MonitorFromWindow(hwnd,MONITOR_DEFAULTTONEAREST),&monitor)){
            auto limits=reinterpret_cast<MINMAXINFO*>(lParam);
            limits->ptMaxPosition={monitor.rcWork.left-monitor.rcMonitor.left,monitor.rcWork.top-monitor.rcMonitor.top};
            limits->ptMaxSize={monitor.rcWork.right-monitor.rcWork.left,monitor.rcWork.bottom-monitor.rcWork.top};
        }
        return 0;
    }
    if(message==WM_NCCALCSIZE&&lParam){
        // wxWidgets also sends this message for pending offscreen geometry.
        // Do not clip those temporary rectangles against absolute monitor bounds.
        return 0; // The custom dark header starts at the actual window top.
    }
    if(message==WM_NCHITTEST){
        if(::IsZoomed(hwnd))return HTCLIENT;
        RECT bounds{};::GetWindowRect(hwnd,&bounds);
        int x=static_cast<short>(LOWORD(lParam)),y=static_cast<short>(HIWORD(lParam)),edge=FromDIP(6);
        bool left=x>=bounds.left&&x<bounds.left+edge,right=x<bounds.right&&x>=bounds.right-edge;
        bool top=y>=bounds.top&&y<bounds.top+edge,bottom=y<bounds.bottom&&y>=bounds.bottom-edge;
        if(top)return left?HTTOPLEFT:right?HTTOPRIGHT:HTTOP;
        if(bottom)return left?HTBOTTOMLEFT:right?HTBOTTOMRIGHT:HTBOTTOM;
        if(left)return HTLEFT;if(right)return HTRIGHT;
        return HTCLIENT;
    }
    return wxFrame::MSWWindowProc(message,wParam,lParam);
}
#endif
