// Copyright (c) 2026 Shengao Karaoke Studio contributors. MIT.
#pragma once
#include <libaegisub/signal.h>
#include <libaegisub/cajun/elements.h>
#include <wx/scrolwin.h>
#include <wx/timer.h>
#include <filesystem>
#include <map>
#include <string>
#include <vector>
#include <utility>
#include <array>
#include <functional>
#include "studio_theme.h"

namespace agi { struct Context; }
class AssDialogue;
class wxChoice;
class wxTextCtrl;
class wxStaticText;
class wxCheckBox;
class wxGrid;
class wxProcess;
class wxProcessEvent;
class wxSimplebook;
class wxToggleButton;
class wxGauge;
class wxButton;
class wxListBox;
class wxDialog;
class wxSpinCtrl;
class wxBoxSizer;

class StudioPanel final : public StudioSurface, private agi::signal::ConnectionScope {
    agi::Context *context;
    wxChoice *provider;
    wxTextCtrl *kana, *romaji, *translation;
    wxCheckBox *locked;
    wxCheckBox *reviewed;
    wxCheckBox *show_ruby, *show_romaji, *show_translation;
    wxCheckBox *loop;
    wxCheckBox *local_range;
    wxGrid *units;
    wxStaticText *status;
    wxSimplebook *pages = nullptr;
    wxBoxSizer *line_navigation=nullptr;
    std::array<StudioButton*,4> stages{};
    wxStaticText *overview = nullptr, *current_label = nullptr, *dirty_label = nullptr;
    wxStaticText *quality_summary = nullptr, *preview_label = nullptr;
    wxGauge *task_progress = nullptr;
    StudioButton *cancel_button = nullptr, *save_button = nullptr;
    StudioButton *review_button = nullptr;
    wxListBox *issues = nullptr;
    wxChoice *issue_filter = nullptr;
    wxChoice *segment_scope = nullptr;
    wxChoice *timing_target=nullptr,*timing_step=nullptr;
    wxSpinCtrl *timing_begin=nullptr,*timing_end=nullptr;
    wxStaticText *reading_evidence=nullptr;
    wxCheckBox *auto_focus=nullptr;
    bool timing_dirty=false;
    int timing_current=-1;
    bool transcript_verified=false;
    StudioButton *pause_button=nullptr;
    std::vector<int> issue_ids;
    std::vector<wxWindow*> task_actions;
    bool preview_active = false, preview_stale = false;
    bool has_pending_result = false;
    std::filesystem::path pending_task;
    wxTimer timer;
    wxTimer loop_timer;
    wxProcess *process = nullptr;
    long pid = 0;
    int active_id = -1;
    bool fields_dirty = false;
    bool loading = false;
    std::string fields_snapshot;
    std::filesystem::path task_dir, result_file;
    std::filesystem::path test_worker_home;
    std::string worker_stderr, worker_payload;
    size_t request_bytes = 0, request_sent = 0;
    int worker_exit = 0;
    bool test_worker = false;
    std::string action;
    std::map<int,std::string> snapshots;
    json::UnknownElement ReadLine(AssDialogue *line);
    json::Array ReadLines(bool selected);
    void WriteLine(AssDialogue *line, json::UnknownElement const& value, bool update_times);
    void RefreshLine();
    void BuildWorkspace();
    void PauseDialog(std::function<int(wxDialog&)> const& inspect = {});
    void BeginnerGuide(std::function<int(wxDialog&)> const& inspect = {});
    void ShowStage(int stage);
    void UpdateOverview();
    void SetStatus(wxString const& message);
    void MarkDirty();
    void UpdateBusy();
    void RefreshChecks();
    void Navigate(int direction,bool unreviewed=false);
    void SelectLine(int id);
    void OffsetDialog();
    void ApplyOffset(int delta,bool selected);
    void OpenMedia();
    void ImportLrc();
    void TaskHistory();
    void ReviewPending();
    void RecordTask(json::Object const& request);
    json::UnknownElement RestoreTask(std::filesystem::path const& folder);
    void SaveFields();
    void DiscardFields();
    void Configure();
    void ShowConfigure(json::UnknownElement const& settings);
    void ImportLyrics();
    void ImportLyricsText(wxString const& text,bool replace);
    void MatchExisting();
    void LocalSegment(std::string const& mode,bool incomplete_only=false);
    void SplitWord();
    void MergeWord();
    void CommitWordEdit(json::UnknownElement const& value);
    void BuildCalibration(wxWindow *parent,wxBoxSizer *layout);
    void RefreshCalibration(bool reset=false);
    void ApplyCalibration(int edge=0,int amount=0);
    void AuditionCalibration(int edge);
    void ConfirmNext();
    void RefineDialog(bool use_llm=false,std::function<int(wxDialog&)> const& inspect = {});
    json::UnknownElement RecentTranscript();
    void RunRefinement(bool use_llm,int gap_ms,std::filesystem::path const& source = {},bool preserve_legacy=false,bool preserve_manual=true);
    void ImportProject();
    void Start(std::string const& action, bool selected=true);
    void Launch(json::Object request);
    void Poll(wxTimerEvent&);
    void DrainWorker();
    void SendWorkerRequest();
    void EndProcess(wxProcessEvent&);
    void Review(json::UnknownElement const& result,std::function<int(wxDialog&)> const& inspect = {});
    std::pair<int,int> ApplyReviewed(json::UnknownElement const& result, std::vector<bool> const& checked);
    void LoadPreview(std::filesystem::path const& path);
    void Export(bool resolved);
    void Preview();
    void Cancel();
public:
    StudioPanel(wxWindow *parent, agi::Context *context);
    ~StudioPanel();
    bool HasRunningTask() const { return pid != 0; }
    bool HasPendingChanges() const { return fields_dirty || timing_dirty; }
    bool FlushChanges();
    bool PrepareClose(std::function<int(bool running)> const& decision = {});
    bool OpenStudioFile(std::filesystem::path const& path);
    bool OpenProject(std::filesystem::path const& path);
    void ImportLrcFile(std::filesystem::path const& path);
    json::UnknownElement DescribeLine(AssDialogue *line) { return ReadLine(line); }
    void GoToStage(int stage) { ShowStage(stage); }
    void AddMedia() { OpenMedia(); }
    void PasteLyrics() { ImportLyrics(); }
    void ShowGuide() { BeginnerGuide(); }
    std::pair<wxString,int> NextStep();
    void DoNextStep();
    void EditCurrent();
    void UpdateCurrent(wxString const& text,int start,int end,bool confirmed,bool protect);
    void FocusTiming(bool word=false);
    void StopAudition();
    // Offline developer verification, invoked only by the explicit self-test command.
    void RunIntegrationTests(std::filesystem::path const& folder);
};
