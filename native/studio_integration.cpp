// Copyright (c) 2026 Shengao Karaoke Studio contributors. MIT.
// Runs the actual editor services on synthetic fixtures, without desktop input.
#include "studio_panel.h"
#include "studio_workflow.h"
#include "studio_shell.h"
#include "studio_editing.h"
#include "studio_pauses.h"
#include "ass_dialogue.h"
#include "ass_file.h"
#include "ass_karaoke.h"
#include "async_video_provider.h"
#include "audio_controller.h"
#include "audio_box.h"
#include "audio_display.h"
#include "audio_karaoke.h"
#include "audio_timing.h"
#include "frame_main.h"
#include "include/aegisub/context.h"
#include "project.h"
#include "options.h"
#include "selection_controller.h"
#include "subs_controller.h"
#include "video_controller.h"
#include "video_frame.h"
#include "video_display.h"
#include <libaegisub/ass/karaoke.h>
#include <libaegisub/json.h>
#include <wx/app.h>
#include <wx/checkbox.h>
#include <wx/button.h>
#include <wx/dialog.h>
#include <wx/choice.h>
#include <wx/checklst.h>
#include <wx/dnd.h>
#include <wx/image.h>
#include <wx/textctrl.h>
#include <wx/grid.h>
#include <wx/simplebook.h>
#include <wx/tglbtn.h>
#include <wx/dcmemory.h>
#include <wx/process.h>
#include <wx/spinctrl.h>
#include <wx/utils.h>
#include <algorithm>
#include <fstream>
#include <sstream>
#include <stdexcept>
#ifdef _WIN32
#include <windows.h>
#endif

namespace {
std::string encoded(json::UnknownElement const& value) {std::ostringstream out;agi::JsonWriter::Write(value,out);return out.str();}
json::UnknownElement parsed(std::string const& value) {std::istringstream in(value);return agi::json_util::parse(in);}
std::string field(json::UnknownElement const& value,char const *key) {return static_cast<json::String const&>(static_cast<json::Object const&>(value).at(key));}
int integer(json::UnknownElement const& value,char const *key) {return int(static_cast<json::Integer const&>(static_cast<json::Object const&>(value).at(key)));}
}

void StudioPanel::RunIntegrationTests(std::filesystem::path const& folder) {
    json::Object report;json::Array passed;
    auto check=[&](bool condition,char const *name){
        if(!condition)throw std::runtime_error(name);
        passed.emplace_back(name);
        std::ofstream(folder/"steps.log",std::ios::app)<<name<<"\n";
    };
    try {
        check(std::filesystem::is_regular_file(folder/".studio-test-fixture"),"isolated_fixture");
        check(NextStep().second==0,"first_use_empty_project_prompts_for_media_before_other_steps");
        if(auto shell=context->studioShell){context->frame->Move(-16000,-16000);context->frame->ShowWithoutActivating();context->frame->SetClientSize(FromDIP(wxSize(1480,900)));ShowStage(0);context->frame->Layout();shell->UpdateState();wxTheApp->Yield(true);auto empty=wxWindow::FindWindowByName("lyrics-empty-state",context->frame);check(empty&&empty->IsShown(),"empty_lyrics_list_explains_how_to_start");auto size=context->frame->GetClientSize();wxBitmap bitmap(size.x,size.y);{wxMemoryDC dc(bitmap);dc.Clear();::PrintWindow(static_cast<HWND>(context->frame->GetHandle()),static_cast<HDC>(dc.GetHDC()),PW_CLIENTONLY|2);::SendMessageW(static_cast<HWND>(context->frame->GetHandle()),WM_PRINT,reinterpret_cast<WPARAM>(dc.GetHDC()),PRF_CLIENT|PRF_CHILDREN|PRF_ERASEBKGND);studio_ui::render_widgets(context->frame,context->frame,dc);}bitmap.SaveFile(wxString((folder/"first-use.png").wstring()),wxBITMAP_TYPE_PNG);}
        {
        // Use the actual wxProcess stdin pipe and worker, not a fabricated completion.
        BeginnerGuide([](wxDialog&){return 1001;});check(context->project->AudioProvider()!=nullptr&&context->project->VideoProvider()==nullptr&&!pid&&ReadLines(false).size()==1,"beginner_demo_opens_real_local_project_and_audio_without_any_api");
        test_worker_home=folder/"native-worker-home";test_worker=true;
        auto await_worker=[&]{auto deadline=wxGetUTCTimeMillis().GetValue()+30000;while(pid&&wxGetUTCTimeMillis().GetValue()<deadline){wxTheApp->Yield(true);wxMilliSleep(10);}check(!pid,"real_worker_process_exits");check(request_sent==request_bytes,"real_worker_receives_complete_large_utf8_request");};
        json::Array long_lines,transcript;
        for(int n=0;n<35;++n){auto value=parsed(R"({"id":"test","text":"真夜中の星空に歌声を届けて","start":0,"end":5000,"units":[]})");auto& object=static_cast<json::Object&>(value);object["id"]=std::to_string(n);object["start"]=n*5000;object["end"]=(n+1)*5000;transcript.emplace_back(parsed(encoded(value)));long_lines.emplace_back(std::move(value));}
        json::Object pipe_request;pipe_request["action"]="match";pipe_request["lines"]=std::move(long_lines);pipe_request["transcript"]=std::move(transcript);
        Launch(std::move(pipe_request));{int stage=pages->GetSelection();DoNextStep();check(pages->GetSelection()==stage,"next_step_while_busy_keeps_the_current_workspace_and_waits_for_review");}await_worker();
        check(std::filesystem::exists(result_file),"real_worker_always_returns_result");
        auto read_worker=[&]{std::ifstream stream(result_file);return agi::json_util::parse(stream);};
        auto pipe_result=read_worker();check(static_cast<json::Boolean const&>(static_cast<json::Object const&>(pipe_result).at("ok"))&&static_cast<json::Array const&>(static_cast<json::Object const&>(pipe_result).at("suggestions")).size()==35,"real_35_line_match_finishes_and_can_be_reviewed");
        check(!cancel_button->IsEnabled()&&task_actions.front()->IsEnabled(),"completed_worker_releases_busy_controls");
        json::Object large_request;large_request["action"]="export";large_request["format"]="txt";large_request["output"]=std::string(wxString((folder/"large-pipe.txt").wstring()).utf8_str());large_request["lines"]=json::Array();large_request["padding"]=std::string(300000,'x');
        Launch(std::move(large_request));await_worker();auto large_result=read_worker();check(static_cast<json::Boolean const&>(static_cast<json::Object const&>(large_result).at("ok")),"real_300kb_request_survives_multiple_pipe_cycles");
        json::Object failure_request;failure_request["action"]="unsupported-test-action";Launch(std::move(failure_request));await_worker();auto failure_result=read_worker();check(!static_cast<json::Boolean const&>(static_cast<json::Object const&>(failure_result).at("ok"))&&!pid&&task_actions.front()->IsEnabled(),"worker_failure_returns_message_and_releases_controls");
        {std::ofstream diagnostic(folder/"worker-pipe-verification.json");std::ifstream input(task_dir/"process.json");diagnostic<<input.rdbuf();}
        has_pending_result=false;UpdateBusy();
        test_worker=false;
        }
        std::ifstream input(folder/"project.json");auto project=agi::json_util::parse(input);
        auto const& fixture=static_cast<json::Array const&>(static_cast<json::Object const&>(project).at("lines")).front();
        auto line=&*context->ass->Events.begin();
        WriteLine(line,fixture,true);
        context->ass->Commit("Test fixture",AssFile::COMMIT_DIAG_FULL|AssFile::COMMIT_EXTRADATA);
        context->selectionController->SetSelectionAndActive({line},line);RefreshLine();
        auto original=ReadLine(line);
        check(field(original,"text")==field(fixture,"text"),"native_annotation_read_write");
        auto const& original_units=static_cast<json::Array const&>(static_cast<json::Object const&>(original).at("units"));
        auto const& original_parts=static_cast<json::Array const&>(static_cast<json::Object const&>(original_units.front()).at("highlights"));
        check(original_parts.size()==2&&field(original_parts[0],"kana")=="きょ"&&field(original_parts[1],"kana")=="う"&&integer(original_parts[1],"start")==1800,"multiple_mora_preserve_text_and_timing");

        auto protected_fixture=studio_workflow::copy(fixture);auto& protected_object=static_cast<json::Object&>(protected_fixture);protected_object["reviewed"]=true;
        auto& protected_units=static_cast<json::Array&>(protected_object.at("units"));static_cast<json::Object&>(protected_units.front())["locked"]=true;
        WriteLine(line,protected_fixture,true);line->Text="{\\bord3\\i1}"+std::string(line->Text);
        context->ass->Commit("Styled fixture",AssFile::COMMIT_DIAG_FULL|AssFile::COMMIT_EXTRADATA);RefreshLine();
        auto styled_text=std::string(line->Text);translation->ChangeValue(L"只修改译文");units->SetCellValue(0,2,L"kyo-u");MarkDirty();
        ShowStage(1);ShowStage(2);
        check(fields_dirty&&translation->GetValue()==L"只修改译文"&&save_button->IsEnabled(),"workflow_stage_switch_preserves_draft");
        SaveFields();check(std::string(line->Text)==styled_text,"metadata_edit_preserves_ass_override_tags");
        auto after_metadata=ReadLine(line);auto const& metadata_units=static_cast<json::Array const&>(static_cast<json::Object const&>(after_metadata).at("units"));
        check(static_cast<json::Boolean const&>(static_cast<json::Object const&>(metadata_units.front()).at("locked")),"metadata_edit_preserves_unit_lock");
        units->SetCellValue(0,1,L"き|ょう");MarkDirty();SaveFields();
        auto resplit=ReadLine(line);auto const& resplit_units=static_cast<json::Array const&>(static_cast<json::Object const&>(resplit).at("units"));
        auto const& resplit_parts=static_cast<json::Array const&>(static_cast<json::Object const&>(resplit_units.front()).at("highlights"));
        check(field(resplit_parts.front(),"kana")=="き"&&field(resplit_parts.back(),"kana")=="ょう","changed_mora_partition_does_not_reuse_old_parts");
        check(!static_cast<json::Boolean const&>(static_cast<json::Object const&>(resplit).at("reviewed")),"changed_mora_partition_resets_review");
        WriteLine(line,fixture,true);context->ass->Commit("Restore fixture",AssFile::COMMIT_DIAG_FULL|AssFile::COMMIT_EXTRADATA);RefreshLine();

        auto multiline=parsed(R"({"text":"歌\n空","start":1000,"end":6000,"units":[]})");
        WriteLine(line,multiline,true);
        check(field(ReadLine(line),"text")=="歌\n空","ass_multiline_roundtrip");
        WriteLine(line,fixture,true);

        AssDialogue split_line;split_line.Start=1000;split_line.End=6000;split_line.Text="{\\kf300}かな{\\kf200}う";
        agi::ass::Karaoke split;SetKaraokeLine(split,&split_line);
        auto split_original=split.GetText();split.AddSplit(0,3);
        check(split.size()==3,"native_syllable_split");
        split.RemoveSplit(1);
        check(split.size()==2&&split.GetText()==split_original,"native_syllable_merge");

        wxArrayString names;names.Add(wxString((folder/"test-video.mp4").wstring()));
        auto drop=dynamic_cast<wxFileDropTarget*>(context->frame->GetDropTarget());
        check(drop&&drop->OnDropFiles(0,0,names),"video_drop_handler_accepted");
        wxTheApp->ProcessPendingEvents();
        check(context->project->VideoProvider()!=nullptr,"video_drop_decoder_loaded");
        check(context->project->AudioProvider()!=nullptr,"video_audio_loaded");
        auto video=context->project->VideoProvider();
        check(video->GetWidth()==1280&&video->GetHeight()==720&&video->GetFrameCount()==200,"video_properties");
        {
            test_worker=true;
            auto await_local=[&]{auto deadline=wxGetUTCTimeMillis().GetValue()+30000;while(pid&&wxGetUTCTimeMillis().GetValue()<deadline){wxTheApp->Yield(true);wxMilliSleep(10);}check(!pid&&std::filesystem::exists(result_file),"japanese_worker_finishes_with_real_native_ipc");std::ifstream stream(result_file);return agi::json_util::parse(stream);};
            LocalSegment("mora");auto segmented=await_local();check(static_cast<json::Boolean const&>(static_cast<json::Object const&>(segmented).at("ok")),"offline_mora_dictionary_job_succeeds");
            check(ApplyReviewed(segmented,{true}).first==1,"offline_segmentation_applies_only_after_review");
            auto sung=ReadLine(context->selectionController->GetActiveLine());auto const& sung_units=static_cast<json::Array const&>(static_cast<json::Object const&>(sung).at("units"));check(sung_units.size()==3&&static_cast<json::Array const&>(static_cast<json::Object const&>(sung_units.back()).at("highlights")).size()==3,"native_morae_preserve_kanji_words_and_split_readings");
            context->subsController->Undo();line=context->selectionController->GetActiveLine();RefreshLine();
            auto manual_words=studio_editing::merge(ReadLine(line),0);CommitWordEdit(manual_words);check(static_cast<json::Array const&>(static_cast<json::Object const&>(ReadLine(line)).at("units")).size()==2,"word_merge_updates_actual_document");context->subsController->Undo();line=context->selectionController->GetActiveLine();RefreshLine();
            units->SetGridCursor(1,0);translation->ChangeValue(L"先保留正在编辑的译文");MarkDirty();MergeWord();auto merged=ReadLine(line);auto const& merged_units=static_cast<json::Array const&>(static_cast<json::Object const&>(merged).at("units"));check(merged_units.size()==2&&field(merged_units.back(),"text")=="も歌う"&&field(merged,"translation")=="先保留正在编辑的译文","merge_button_keeps_selected_row_after_flushing_draft");context->subsController->Undo();context->subsController->Undo();line=context->selectionController->GetActiveLine();RefreshLine();
            auto split_word=studio_editing::split(ReadLine(line),0,{"今","日"},{"きょ","う"});CommitWordEdit(split_word);check(static_cast<json::Array const&>(static_cast<json::Object const&>(ReadLine(line)).at("units")).size()==4,"word_split_updates_document_and_can_be_undone");context->subsController->Undo();line=context->selectionController->GetActiveLine();RefreshLine();
            json::Object request;request["action"]="match";request["lines"]=ReadLines(true);request["transcript"]=parsed(R"([{"id":"a","text":"今 日 も 歌 う","start":1000,"end":3000,"units":[]},{"id":"b","text":"今日も歌う","start":5000,"end":7500,"units":[]}])");snapshots[line->Id]=encoded(ReadLine(line));Launch(std::move(request));auto matched=await_local();
            auto before=encoded(ReadLine(line));int inspected=0;
            auto inspect=[&](wxDialog& dialog){auto candidates=dynamic_cast<wxChoice*>(wxWindow::FindWindowByName(L"review-candidates",&dialog));auto rows=dynamic_cast<wxCheckListBox*>(wxWindow::FindWindowByName(L"review-rows",&dialog));auto play=dynamic_cast<wxButton*>(wxWindow::FindWindowByName(L"review-play",&dialog));auto stop=dynamic_cast<wxButton*>(wxWindow::FindWindowByName(L"review-stop",&dialog));
                dialog.Move(-16000,-16000);dialog.ShowWithoutActivating();dialog.Layout();wxTheApp->Yield(true);
                check(candidates&&candidates->GetCount()==3&&candidates->IsEnabled(),"review_exposes_both_chorus_positions");candidates->SetSelection(2);wxCommandEvent choice(wxEVT_CHOICE,candidates->GetId());choice.SetInt(2);candidates->ProcessWindowEvent(choice);check(rows->IsChecked(0)&&encoded(ReadLine(line))==before,"choosing_candidate_checks_row_without_changing_project");
                wxCommandEvent listen(wxEVT_BUTTON,play->GetId());play->ProcessWindowEvent(listen);check(context->audioController->IsPlaying(),"review_auditions_candidate_without_cloud");wxCommandEvent stop_event(wxEVT_BUTTON,stop->GetId());stop->ProcessWindowEvent(stop_event);check(!context->audioController->IsPlaying(),"review_stop_button_stops_preview");
                for(auto dimensions:{wxSize(700,540),wxSize(850,640)}){dialog.SetSize(dimensions);dialog.Layout();auto client=dialog.GetClientSize();bool fits=true;for(auto child:dialog.GetChildren())if(child->IsShown())fits&=child->GetRect().GetBottom()<=client.y&&child->GetRect().GetRight()<=client.x;check(fits,"review_choices_and_confirm_buttons_fit_resizable_dialog");}
                auto size=dialog.GetSize();wxBitmap image(size.x,size.y);{wxMemoryDC dc(image);dc.SetBackground(*wxWHITE_BRUSH);dc.Clear();::PrintWindow(static_cast<HWND>(dialog.GetHandle()),static_cast<HDC>(dc.GetHDC()),2);::SendMessageW(static_cast<HWND>(dialog.GetHandle()),WM_PRINT,reinterpret_cast<WPARAM>(dc.GetHDC()),PRF_CLIENT|PRF_CHILDREN|PRF_NONCLIENT|PRF_ERASEBKGND);}image.SaveFile(wxString((folder/"review-candidates.png").wstring()),wxBITMAP_TYPE_PNG);dialog.Hide();
                ++inspected;return inspected==1?wxID_CANCEL:wxID_OK;
            };
            Review(matched,inspect);check(encoded(ReadLine(line))==before,"cancelling_review_keeps_original_text_and_times");Review(matched,inspect);line=context->selectionController->GetActiveLine();check(int(line->Start)==5000&&field(ReadLine(line),"text")==field(fixture,"text"),"confirmed_candidate_changes_time_but_never_uses_asr_spaces");
            context->subsController->Undo();line=context->selectionController->GetActiveLine();RefreshLine();auto media_before=context->project->VideoName();ImportLyricsText(L"  今日 も、\n歌う！  \n",true);auto imported=ReadLines(false);check(imported.size()==2&&field(imported.front(),"text")=="  今日 も、"&&field(imported.back(),"text")=="歌う！  "&&context->project->VideoName()==media_before,"replacing_draft_with_original_preserves_spaces_and_open_media");context->subsController->Undo();line=context->selectionController->GetActiveLine();RefreshLine();check(field(ReadLine(line),"text")==field(fixture,"text"),"original_lyric_replacement_is_undoable");has_pending_result=false;UpdateBusy();test_worker=false;
        }

        auto zoom_before=context->audioBox->StudioDisplay()->GetZoomLevel();auto range_before=context->audioController->GetPrimaryPlaybackRange();
        context->audioBox->StudioSetHorizontalZoom(4);
        check(context->audioBox->StudioDisplay()->GetZoomLevel()==4&&context->audioController->GetPrimaryPlaybackRange().begin()==range_before.begin()&&context->audioController->GetPrimaryPlaybackRange().end()==range_before.end(),"horizontal_zoom_control_preserves_audio_timing");
        context->audioBox->StudioSetHorizontalZoom(zoom_before);
        auto amplitude_before=OPT_GET("Audio/Zoom/Vertical")->GetInt();context->audioBox->StudioSetAmplitude(65);
        check(context->audioController->GetPrimaryPlaybackRange().begin()==range_before.begin()&&context->audioController->GetPrimaryPlaybackRange().end()==range_before.end(),"waveform_height_control_preserves_audio_timing");context->audioBox->StudioSetAmplitude(amplitude_before);

        line->Text="{\\bord3}"+std::string(line->Text);context->ass->Commit("Offset fixture",AssFile::COMMIT_DIAG_FULL);RefreshLine();
        auto before_offset=std::string(line->Text);ApplyOffset(250,true);
        check(int(line->Start)==1250&&std::string(line->Text)==before_offset,"batch_offset_preserves_ass_tags_and_relative_timing");
        auto offset_data=ReadLine(line);auto const& offset_units=static_cast<json::Array const&>(static_cast<json::Object const&>(offset_data).at("units"));
        check(integer(offset_units.front(),"start")==1250,"batch_offset_moves_mora_origin");
        context->subsController->Undo();line=context->selectionController->GetActiveLine();check(int(line->Start)==1000,"batch_offset_undo");
        bool negative_rejected=false;auto unchanged=encoded(ReadLine(line));try{ApplyOffset(-2000,true);}catch(std::exception const&){negative_rejected=true;}
        check(negative_rejected&&encoded(ReadLine(line))==unchanged,"negative_offset_leaves_document_unchanged");
        bool precision_rejected=false;try{ApplyOffset(7,true);}catch(std::exception const&){precision_rejected=true;}
        check(precision_rejected&&encoded(ReadLine(line))==unchanged,"offset_rejects_precision_unsupported_by_ass");
        auto early_value=parsed(R"({"text":"空","start":500,"end":900,"units":[]})");auto early_line=new AssDialogue;WriteLine(early_line,early_value,true);context->ass->Events.push_back(*early_line);context->ass->Commit("Atomic offset fixture",AssFile::COMMIT_DIAG_ADDREM|AssFile::COMMIT_EXTRADATA);
        context->selectionController->SetSelectionAndActive({line,early_line},line);bool batch_rejected=false;try{ApplyOffset(-700,true);}catch(std::exception const&){batch_rejected=true;}
        check(batch_rejected&&int(line->Start)==1000&&int(early_line->Start)==500,"offset_batch_validates_all_lines_before_mutation");
        context->selectionController->SetSelectionAndActive({line},line);context->ass->Events.erase(context->ass->Events.iterator_to(*early_line));delete early_line;context->ass->Commit("Remove offset fixture",AssFile::COMMIT_DIAG_ADDREM);

        context->karaoke->SetEnabled(true);
        {
            // Reproduce the reported Japanese strip: empty timing tags used to
            // create narrow cells and two dividers between the real words.
            auto gapped=parsed(R"({"text":"真夜中のネオンサインが君を抱きしめて","start":1000,"end":5200,"units":[{"text":"真夜中","start":1100,"end":1500},{"text":"の","start":1500,"end":1600},{"text":"ネオンサイン","start":1650,"end":2650},{"text":"が","start":2650,"end":2750},{"text":"君","start":4250,"end":4550},{"text":"を","start":4550,"end":4650},{"text":"抱きしめ","start":4650,"end":5050},{"text":"て","start":5100,"end":5200}]})");
            WriteLine(line,gapped,true);context->ass->Commit("Gap display fixture",AssFile::COMMIT_DIAG_FULL|AssFile::COMMIT_EXTRADATA);
            check(context->karaoke->StudioSplitLines().size()==7,"karaoke_eight_words_have_only_seven_dividers_despite_short_and_long_pauses");
            auto raw=std::string(line->Text);check(context->karaoke->StudioPendingText()==raw,"karaoke_compact_display_preserves_all_ass_timing_tags");
            auto roundtrip=ReadLine(line);auto const& words=static_cast<json::Array const&>(static_cast<json::Object const&>(roundtrip).at("units"));
            check(words.size()==8&&integer(words[4],"start")==4250&&integer(words[3],"end")==2750,"karaoke_compact_display_retains_1500ms_rest_and_original_word_times");
            auto area=context->karaoke->StudioSplitArea();wxBitmap bitmap(area->GetClientSize());{wxMemoryDC dc(bitmap);context->karaoke->StudioRender(dc);}
            check(bitmap.ConvertToImage().SaveFile(wxString((folder/"karaoke-single-boundaries.png").wstring()),wxBITMAP_TYPE_PNG),"karaoke_single_boundary_strip_render_saved");
            line->Text="{\\k10}{\\kf50}今日{\\k5}{\\k8}{\\kf20}も{\\k30}";line->Start=1000;line->End=2230;
            context->ass->Commit("Consecutive gap fixture",AssFile::COMMIT_DIAG_FULL);
            raw=std::string(line->Text);auto click=[&](int x){wxMouseEvent event(wxEVT_LEFT_DOWN);event.SetPosition(wxPoint(x,10));area->GetEventHandler()->ProcessEvent(event);};
            check(context->karaoke->StudioSplitLines().size()==1,"karaoke_multiple_empty_tags_share_one_word_boundary");
            click(context->karaoke->StudioSplitLines().front());
            check(context->karaoke->StudioSplitLines().empty()&&std::string(line->Text)==raw,"karaoke_boundary_click_merges_once_without_premature_commit");
            auto button=[&](char const *name){auto control=wxWindow::FindWindowByName(name,context->karaoke);check(control!=nullptr,"karaoke_pending_edit_button_exists");wxCommandEvent event(wxEVT_BUTTON,control->GetId());control->ProcessWindowEvent(event);};
            button("karaoke-cancel");check(context->karaoke->StudioPendingText()==raw&&context->karaoke->StudioSplitLines().size()==1,"karaoke_cancel_restores_words_and_all_pause_tags");
            click(context->karaoke->StudioSplitLines().front());button("karaoke-accept");
            auto joined=ParseKaraokeSyllables(line);check(joined.size()==3&&joined[1].text=="今日も"&&joined[1].duration==830&&joined[2].duration==300,"karaoke_accept_joins_gap_and_words_preserving_total_time_and_end_rest");
            context->subsController->Undo();line=context->selectionController->GetActiveLine();check(std::string(line->Text)==raw&&context->karaoke->StudioSplitLines().size()==1,"karaoke_gap_merge_undo_restores_exact_source");
            line->Text="{\\k10}{\\kf10}の{\\k9}{\\kf60}ネオンサイン{\\kf10}を";line->Start=1000;line->End=1990;
            context->ass->Commit("Split after gap fixture",AssFile::COMMIT_DIAG_FULL);raw=std::string(line->Text);
            auto dividers=context->karaoke->StudioSplitLines();check(dividers.size()==2,"karaoke_word_split_fixture_has_two_visible_boundaries");
            int cell=(dividers[1]-dividers[0])/6;click(0);
            check(context->karaoke->StudioPendingText()==raw,"karaoke_word_start_click_cannot_insert_an_empty_syllable");
            check(context->karaoke->StudioDisplayText()==L"のネオンサインを","karaoke_display_contains_exact_lyrics_without_inserted_spaces");
            click(dividers[0]+cell*3);AssDialogue pending;pending.Start=1000;pending.End=1990;pending.Text=context->karaoke->StudioPendingText();
            auto internal=ParseKaraokeSyllables(&pending);
            check(context->karaoke->StudioSplitLines().size()==3&&internal.size()==6&&internal[2].duration==90&&internal[3].text=="ネオン"&&internal[4].text=="サイン"&&std::string(line->Text)==raw,"karaoke_actual_word_click_after_hidden_gap_splits_correct_japanese_character");
            button("karaoke-cancel");check(context->karaoke->StudioPendingText()==raw,"karaoke_internal_split_cancel_restores_exact_word_and_pause");
            line->Text="{\\k10} {\\kf50}今日{\\k5}　{\\kf20}も{\\k30} ";line->Start=1000;line->End=2150;
            context->ass->Commit("Whitespace gap fixture",AssFile::COMMIT_DIAG_FULL);
            raw=std::string(line->Text);check(context->karaoke->StudioSplitLines().size()==1&&context->karaoke->StudioPendingText()==raw,"karaoke_original_whitespace_has_no_extra_cells_and_is_not_removed");
            line->Text="{\\k10}{\\k20}　";line->Start=1000;line->End=1300;context->ass->Commit("Silent fixture",AssFile::COMMIT_DIAG_FULL);
            raw=context->karaoke->StudioPendingText();click(2);check(context->karaoke->StudioSplitLines().empty()&&context->karaoke->StudioPendingText()==raw,"karaoke_all_silence_strip_is_empty_and_click_safe");
            WriteLine(line,fixture,true);context->ass->Commit("Restore fixture",AssFile::COMMIT_DIAG_FULL|AssFile::COMMIT_EXTRADATA);RefreshLine();
        }
        #include "studio_correction_test.inc"
        #include "studio_usability_test.inc"
        auto timing=context->audioController->GetTimingController();
        auto before=timing->GetPrimaryPlaybackRange();
        timing->ModifyLength(-2,false);timing->Commit();
        check(timing->GetPrimaryPlaybackRange().end()==before.end()-20,"keyboard_timing_adjustment");
        auto modified=std::string(context->selectionController->GetActiveLine()->Text);
        context->subsController->Undo();
        check(std::string(context->selectionController->GetActiveLine()->Text)!=modified,"native_undo");
        context->subsController->Redo();
        check(std::string(context->selectionController->GetActiveLine()->Text)==modified,"native_redo");
        line=context->selectionController->GetActiveLine();WriteLine(line,fixture,true);
        context->ass->Commit("Restore fixture",AssFile::COMMIT_DIAG_FULL|AssFile::COMMIT_EXTRADATA);
        RefreshLine();
        auto canonical=ReadLine(line);int id=line->Id;
        auto suggestion=parsed(encoded(canonical));
        static_cast<json::Object&>(suggestion)["translation"]="自动建议译文";
        json::Array candidates;candidates.emplace_back(parsed(encoded(suggestion)));
        json::Object result_object;result_object["suggestions"]=std::move(candidates);
        json::UnknownElement result(std::move(result_object));
        action="annotate";snapshots[id]=encoded(canonical);
        check(ApplyReviewed(result,{false}).first==0,"unchecked_suggestion_not_applied");
        auto locked_value=parsed(encoded(canonical));static_cast<json::Object&>(locked_value)["locked"]=true;
        WriteLine(line,locked_value,true);snapshots[id]=encoded(ReadLine(line));
        check(ApplyReviewed(result,{true})==std::pair<int,int>{0,1},"locked_line_preserved");
        WriteLine(line,canonical,true);snapshots[id]=encoded(ReadLine(line));
        line->Text=std::string(line->Text)+"追記";
        check(ApplyReviewed(result,{true})==std::pair<int,int>{0,1},"edited_line_preserved");
        WriteLine(line,canonical,true);RefreshLine();snapshots[id]=encoded(ReadLine(line));fields_dirty=true;
        check(ApplyReviewed(result,{true})==std::pair<int,int>{0,1},"unsaved_sidebar_preserved");fields_dirty=false;
        auto invalid=parsed(encoded(suggestion));static_cast<json::Object&>(invalid)["end"]=0;
        json::Array invalid_batch;invalid_batch.emplace_back(parsed(encoded(suggestion)));invalid_batch.emplace_back(std::move(invalid));
        json::Object malformed_object;malformed_object["suggestions"]=std::move(invalid_batch);
        json::UnknownElement malformed(std::move(malformed_object));bool rejected=false;
        try{ApplyReviewed(malformed,{true,true});}catch(std::exception const&){rejected=true;}
        check(rejected&&encoded(ReadLine(line))==encoded(canonical),"invalid_batch_does_not_partially_apply");
        check(ApplyReviewed(result,{true})==std::pair<int,int>{1,0},"reviewed_suggestion_applied");
        check(!context->ass->GetScriptInfo("Shengao API History").empty(),"api_history_saved");

        // Exercise the real sidebar flush hook and native ASS save/load metadata.
        RefreshLine();translation->ChangeValue(L"人工保存译文");fields_dirty=true;
        check(FlushChanges(),"sidebar_flush");
        auto saved=encoded(ReadLine(line));
        auto history_folder=folder/"recover-test";std::filesystem::create_directories(history_folder);task_dir=history_folder;
        json::Object record;record["action"]="annotate";record["provider"]="elevenlabs";record["key"]="sensitive-test-value-never-persist";
        json::Array record_lines;record_lines.emplace_back(ReadLine(line));record["lines"]=std::move(record_lines);RecordTask(record);
        std::ifstream recorded(history_folder/"task.json");std::string recorded_text((std::istreambuf_iterator<char>(recorded)),{});
        check(recorded_text.find("sensitive-test-value-never-persist")==std::string::npos,"task_metadata_does_not_save_api_keys");
        auto history_suggestion=ReadLine(line);static_cast<json::Object&>(history_suggestion)["translation"]="历史恢复译文";
        json::Array history_suggestions;history_suggestions.emplace_back(std::move(history_suggestion));json::Object history_result;history_result["ok"]=true;history_result["suggestions"]=std::move(history_suggestions);
        {std::ofstream output(history_folder/"result.json");agi::JsonWriter::Write(history_result,output);}
        result_file=history_folder/"result.json";action="annotate";wxProcessEvent completed;
        EndProcess(completed);
        check(has_pending_result&&review_button->IsEnabled()&&field(ReadLine(line),"translation")=="人工保存译文","background_completion_waits_for_user_review");
        context->subsController->Save(agi::fs::path((folder/"roundtrip.ass").wstring()),"UTF-8");
        context->project->LoadSubtitles(agi::fs::path((folder/"roundtrip.ass").wstring()),"UTF-8",false);
        line=context->selectionController->GetActiveLine();
        // AssDialogue IDs are regenerated on reopening; compare persisted content.
        auto reopened=ReadLine(line);auto saved_value=parsed(saved);
        static_cast<json::Object&>(reopened)["id"]="";static_cast<json::Object&>(saved_value)["id"]="";
        check(encoded(reopened)==encoded(saved_value),"ass_metadata_save_reopen");
        check(!context->ass->GetScriptInfo("Shengao API History").empty(),"history_survives_reopen");

        auto restored=RestoreTask(history_folder);
        check(ApplyReviewed(restored,{true})==std::pair<int,int>{1,0}&&field(ReadLine(line),"translation")=="历史恢复译文","history_result_restores_after_reopen_without_cloud");
        bool duplicate_rejected=false;try{ApplyReviewed(restored,{true});}catch(std::exception const&){duplicate_rejected=true;}
        check(duplicate_rejected,"already_applied_task_is_not_applied_twice");
        context->subsController->Undo();line=context->selectionController->GetActiveLine();
        auto saved_manual=ReadLine(line);auto changed_manual=studio_workflow::copy(saved_manual);static_cast<json::Object&>(changed_manual)["translation"]="后来手动修改";WriteLine(line,changed_manual,true);RefreshLine();
        auto changed_restore=RestoreTask(history_folder);
        check(ApplyReviewed(changed_restore,{true})==std::pair<int,int>{0,1}&&field(ReadLine(line),"translation")=="后来手动修改","history_recovery_preserves_later_manual_edits");
        WriteLine(line,saved_manual,true);RefreshLine();
        auto history_locked=studio_workflow::copy(saved_manual);static_cast<json::Object&>(history_locked)["locked"]=true;WriteLine(line,history_locked,true);RefreshLine();
        auto locked_restore=RestoreTask(history_folder);check(ApplyReviewed(locked_restore,{true})==std::pair<int,int>{0,1},"history_recovery_preserves_locks");WriteLine(line,saved_manual,true);RefreshLine();
        auto ambiguous_line=new AssDialogue;WriteLine(ambiguous_line,saved_manual,true);context->ass->Events.push_back(*ambiguous_line);context->ass->Commit("Ambiguous history fixture",AssFile::COMMIT_DIAG_ADDREM|AssFile::COMMIT_EXTRADATA);
        auto ambiguous_restore=RestoreTask(history_folder);check(ApplyReviewed(ambiguous_restore,{true})==std::pair<int,int>{0,1},"history_recovery_rejects_ambiguous_matches");
        context->ass->Events.erase(context->ass->Events.iterator_to(*ambiguous_line));delete ambiguous_line;context->ass->Commit("Remove history fixture",AssFile::COMMIT_DIAG_ADDREM);

        line->Actor="recovery-check";
        context->ass->Commit("Recovery fixture",AssFile::COMMIT_DIAG_META);
        std::filesystem::path recovery;
        // Let the production autosave timer and background writer complete.
        for(int attempt=0;attempt<100&&recovery.empty();++attempt){
            wxMilliSleep(50);wxTheApp->Yield(true);
            auto directory=folder/"autosave";
            if(!std::filesystem::is_directory(directory))continue;
            for(auto const& entry:std::filesystem::directory_iterator(directory)){
                if(!entry.is_regular_file()||!entry.path().filename().string().ends_with(".AUTOSAVE.ass"))continue;
                std::ifstream backup(entry.path(),std::ios::binary);
                std::string content((std::istreambuf_iterator<char>(backup)),{});
                if(content.find("recovery-check")!=std::string::npos)recovery=entry.path();
            }
        }
        check(!recovery.empty(),"production_autosave_created");
        context->project->LoadSubtitles(agi::fs::path(recovery.wstring()),"UTF-8",false);
        line=context->selectionController->GetActiveLine();
        check(field(ReadLine(line),"translation")=="人工保存译文"&&std::string(line->Actor)=="recovery-check","autosave_recovery_restores_annotations");

        auto primary=context->audioController->GetPrimaryPlaybackRange();
        for(double rate:{.5,.75,1.}){
            context->audioController->SetPlaybackRate(rate);context->audioController->SetVolume(0.0);
            context->audioController->PlayPrimaryRange();
            check(context->audioController->IsPlaying(),rate==.5?"playback_half_speed":rate==.75?"playback_three_quarters":"playback_normal");
            context->audioController->Stop();
            auto after=context->audioController->GetPrimaryPlaybackRange();
            check(after.begin()==primary.begin()&&after.end()==primary.end(),"playback_preserves_timing_coordinates");
        }
        loop->SetValue(true);wxTimerEvent tick(loop_timer);
        ProcessEvent(tick);check(context->audioController->IsPlaying(),"loop_restarts_primary_range");
        loop->SetValue(false);context->audioController->Stop();

        context->videoController->JumpToFrame(50);
        video->GetFrame(50,2000,true);wxTheApp->ProcessPendingEvents();
        double received_time=-1;
        auto listener=[&](FrameReadyEvent& event){received_time=event.time;event.Skip();};
        context->videoController->Bind(EVT_FRAME_READY,listener);
        LoadPreview(folder/"resolved.ass");
        auto raw=video->GetFrame(50,2000,true);auto early=video->GetFrame(50,2000);
        auto late=video->GetFrame(100,4000);
        auto difference=[](VideoFrame const& a,VideoFrame const& b){size_t count=0;for(size_t i=0;i<a.data.size();++i)if(a.data[i]!=b.data[i])++count;return count;};
        check(difference(*raw,*early)>500,"native_preview_renders_subtitles");
        check(difference(*early,*late)>50,"native_preview_highlight_changes");
        check(GetImage(*early).SaveFile(wxString((folder/"preview-2000.png").wstring()),wxBITMAP_TYPE_PNG),"preview_image_saved");
        GetImage(*late).SaveFile(wxString((folder/"preview-4000.png").wstring()),wxBITMAP_TYPE_PNG);
        // Check the timestamp actually requested by the preview refresh callback.
        wxTheApp->ProcessPendingEvents();
        context->videoController->Unbind(EVT_FRAME_READY,listener);
        report["preview_refresh_time_ms"]=received_time;
        check(received_time==context->videoController->TimeAtFrame(50),"preview_callback_uses_milliseconds");

        context->ass->Commit("Mark preview stale",AssFile::COMMIT_DIAG_META);check(preview_stale&&!preview_active,"document_edit_marks_preview_stale");
        auto before_lrc=encoded(json::UnknownElement(ReadLines(false)));bool bad_lrc=false;
        try{ImportLrcFile(folder/"invalid.lrc");}catch(std::exception const&){bad_lrc=true;}
        check(bad_lrc&&encoded(json::UnknownElement(ReadLines(false)))==before_lrc,"invalid_lrc_does_not_change_document");
        size_t old_count=context->ass->Events.size();wxArrayString lrc_names;lrc_names.Add(wxString((folder/"import.lrc").wstring()));drop->OnDropFiles(0,0,lrc_names);
        for(int attempt=0;attempt<100&&context->ass->Events.size()==old_count;++attempt){wxTheApp->ProcessPendingEvents();wxMilliSleep(10);}
        report["lrc_rows_before"]=int(old_count);report["lrc_rows_after"]=int(context->ass->Events.size());report["lrc_active_start"]=int(context->selectionController->GetActiveLine()->Start);
        check(context->ass->Events.size()==old_count+2&&int(context->selectionController->GetActiveLine()->Start)==1100,"lrc_drop_imports_offset_timestamps");
        context->subsController->Undo();
        check(context->ass->Events.size()==old_count&&context->selectionController->GetActiveLine()!=nullptr&&int(context->selectionController->GetActiveLine()->Start)==1000,"lrc_import_undo_restores_original_selection");
        context->subsController->Redo();
        check(context->ass->Events.size()==old_count+2&&context->selectionController->GetActiveLine()!=nullptr&&int(context->selectionController->GetActiveLine()->Start)==1100,"lrc_import_redo_restores_imported_selection");
        ShowStage(3);check(!issue_ids.empty(),"workflow_quality_check_lists_actionable_lines");
        auto first_lrc=context->selectionController->GetActiveLine();Navigate(1,true);check(context->selectionController->GetActiveLine()!=first_lrc,"next_unreviewed_navigates_to_next_lyric");
        auto transcript=studio_workflow::copy(fixture);json::Array transcript_lines;transcript_lines.emplace_back(std::move(transcript));json::Object transcript_object;transcript_object["suggestions"]=std::move(transcript_lines);transcript_object["task_id"]="transcription-duplicate-test";json::UnknownElement transcript_result(std::move(transcript_object));action="transcribe";
        auto transcript_count=context->ass->Events.size();ApplyReviewed(transcript_result,{true});bool transcript_duplicate=false;try{ApplyReviewed(transcript_result,{true});}catch(std::exception const&){transcript_duplicate=true;}
        check(transcript_duplicate&&context->ass->Events.size()==transcript_count+1,"transcription_history_cannot_append_twice");context->subsController->Undo();

#ifdef _WIN32
        // Render only our own application widget. No desktop capture or input.
        SelectLine(context->ass->Events.begin()->Id);
        auto shell=context->studioShell;check(shell&&shell->lyrics,"modern_shell_and_cards_created");
        shell->ToggleMaximize();check(context->frame->IsMaximized(),"custom_window_control_maximizes_hidden_test_frame");shell->ToggleMaximize();check(!context->frame->IsMaximized(),"custom_window_control_restores_test_frame");
        auto before_close=encoded(ReadLine(context->selectionController->GetActiveLine()));translation->ChangeValue(L"未保存关闭测试");MarkDirty();
        check(!PrepareClose([](bool){return wxCANCEL;})&&fields_dirty,"close_cancel_keeps_unsaved_draft");
        check(PrepareClose([](bool){return wxNO;})&&!fields_dirty&&encoded(ReadLine(context->selectionController->GetActiveLine()))==before_close,"close_discard_does_not_write_draft");RefreshLine();
        translation->ChangeValue(L"保存后关闭测试");MarkDirty();check(PrepareClose([](bool){return wxYES;})&&!fields_dirty&&field(ReadLine(context->selectionController->GetActiveLine()),"translation")=="保存后关闭测试","close_save_commits_draft_before_leaving");context->subsController->Undo();RefreshLine();
        translation->ChangeValue(L"统一保存按钮测试");MarkDirty();check(save_button->IsEnabled(),"themed_save_enables_for_real_pending_changes");
        wxKeyEvent save_down(wxEVT_KEY_DOWN);save_down.m_keyCode=WXK_SPACE;save_button->ProcessWindowEvent(save_down);
        wxKeyEvent save_up(wxEVT_KEY_UP);save_up.m_keyCode=WXK_SPACE;save_button->ProcessWindowEvent(save_up);
        check(!fields_dirty&&field(ReadLine(context->selectionController->GetActiveLine()),"translation")=="统一保存按钮测试","themed_save_keyboard_activation_commits_draft");
        context->subsController->Undo();RefreshLine();
        shell->lyrics->SetFilter(L"今日",0);check(shell->lyrics->GetItemCount()>=1,"lyric_search_finds_original_text");
        auto first_id=shell->lyrics->IdAt(0);shell->lyrics->Choose(0);check(context->selectionController->GetActiveLine()->Id==first_id,"card_selection_updates_native_timing_selection");
        shell->lyrics->SetFilter(L"no-such-lyric-xyz",0);check(shell->lyrics->GetItemCount()==0&&context->selectionController->GetActiveLine()->Id==first_id,"empty_search_preserves_native_selection");shell->lyrics->SetFilter(L"",0);
        check(!context->frame->GetMenuBar()&&!context->frame->GetToolBar()&&!(context->frame->GetWindowStyleFlag()&wxCAPTION),"default_shell_owns_chrome_without_legacy_menu_toolbar");
        auto editor_line=context->selectionController->GetActiveLine();auto edit_before=ReadLine(editor_line);auto const& edit_object=static_cast<json::Object const&>(edit_before);auto editor_start=int(editor_line->Start),editor_end=int(editor_line->End);
        UpdateCurrent(wxString::FromUTF8(studio_document::text(edit_object,"text")),editor_start+100,editor_end+100,false,false);
        check(int(context->selectionController->GetActiveLine()->Start)==editor_start+100,"compact_line_editor_moves_native_timing");context->subsController->Undo();check(int(context->selectionController->GetActiveLine()->Start)==editor_start,"compact_line_editor_changes_are_undoable");
        bool bad_edit=false;try{UpdateCurrent(L"歌",1000,1000,false,false);}catch(std::exception const&){bad_edit=true;}check(bad_edit,"compact_line_editor_rejects_invalid_timing");
        auto matched_line=context->selectionController->GetActiveLine();auto matched_data=ReadLine(matched_line);auto& matched_object=static_cast<json::Object&>(matched_data);
        matched_object["match"]=parsed(R"({"status":"uncertain","score":0.6,"coverage":0.7,"recognized":"今日","reason":"合成副歌歧义","timing":"rough"})");WriteLine(matched_line,matched_data,true);context->ass->Commit("Match review fixture",AssFile::COMMIT_DIAG_FULL|AssFile::COMMIT_EXTRADATA);
        auto matched_read=ReadLine(matched_line);check(static_cast<json::Object const&>(matched_read).find("match")!=static_cast<json::Object const&>(matched_read).end(),"match_metadata_survives_native_ass_roundtrip");
        shell->lyrics->SetFilter(L"",2);check(shell->lyrics->GetItemCount()==1,"uncertain_match_filter_finds_problem_line");shell->lyrics->SetFilter(L"",0);
        auto match_issues=studio_workflow::inspect(ReadLines(false));check(std::any_of(match_issues.begin(),match_issues.end(),[](auto const& issue){return issue.code=="match";}),"matching_uncertainty_enters_quality_checks");
        context->subsController->Undo();
        shell->ToggleAdvanced();shell->ToggleAdvanced();check(true,"advanced_editor_can_toggle_without_replacing_engine");
        context->frame->SetWindowStyleFlag(context->frame->GetWindowStyleFlag()|wxFRAME_NO_TASKBAR);
        context->frame->Move(-16000,-16000);context->frame->ShowWithoutActivating();wxTheApp->Yield(true);
        auto hwnd=static_cast<HWND>(context->frame->GetHandle());RECT frame_bounds{},client_bounds{};POINT client_origin{0,0};
        ::GetWindowRect(hwnd,&frame_bounds);::GetClientRect(hwnd,&client_bounds);::ClientToScreen(hwnd,&client_origin);
        check(client_origin.y==frame_bounds.top&&client_origin.x==frame_bounds.left&&client_bounds.right==frame_bounds.right-frame_bounds.left,"custom_header_has_no_extra_native_top_strip_or_border");
        auto hit_at=[&](int x,int y){return ::SendMessageW(hwnd,WM_NCHITTEST,0,MAKELPARAM(x,y));};int middle_x=(frame_bounds.left+frame_bounds.right)/2,middle_y=(frame_bounds.top+frame_bounds.bottom)/2;
        check(hit_at(frame_bounds.left+1,frame_bounds.top+1)==HTTOPLEFT&&hit_at(middle_x,frame_bounds.top+1)==HTTOP&&hit_at(frame_bounds.right-1,frame_bounds.top+1)==HTTOPRIGHT&&hit_at(frame_bounds.left+1,middle_y)==HTLEFT&&hit_at(frame_bounds.right-1,middle_y)==HTRIGHT&&hit_at(frame_bounds.left+1,frame_bounds.bottom-1)==HTBOTTOMLEFT&&hit_at(middle_x,frame_bounds.bottom-1)==HTBOTTOM&&hit_at(frame_bounds.right-1,frame_bounds.bottom-1)==HTBOTTOMRIGHT,"custom_frame_preserves_all_eight_resize_edges");
        shell->ToggleMaximize();wxTheApp->Yield(true);::GetClientRect(hwnd,&client_bounds);client_origin={0,0};::ClientToScreen(hwnd,&client_origin);MONITORINFO monitor{sizeof(MONITORINFO)};::GetMonitorInfoW(::MonitorFromWindow(hwnd,MONITOR_DEFAULTTONEAREST),&monitor);
        report["maximized_geometry"]=std::to_string(client_origin.x)+","+std::to_string(client_origin.y)+","+std::to_string(client_bounds.right)+","+std::to_string(client_bounds.bottom)+" work="+std::to_string(monitor.rcWork.left)+","+std::to_string(monitor.rcWork.top)+","+std::to_string(monitor.rcWork.right)+","+std::to_string(monitor.rcWork.bottom);
        auto minimum=context->frame->GetMinSize();auto best=context->frame->GetBestSize();MINMAXINFO limits{};::SendMessageW(hwnd,WM_GETMINMAXINFO,0,reinterpret_cast<LPARAM>(&limits));report["frame_limits"]=std::to_string(minimum.x)+","+std::to_string(minimum.y)+" best="+std::to_string(best.x)+","+std::to_string(best.y)+" track="+std::to_string(limits.ptMinTrackSize.x)+","+std::to_string(limits.ptMinTrackSize.y)+" max="+std::to_string(limits.ptMaxSize.x)+","+std::to_string(limits.ptMaxSize.y);
        check(client_origin.x==monitor.rcWork.left&&client_origin.y==monitor.rcWork.top&&client_origin.x+client_bounds.right==monitor.rcWork.right&&client_origin.y+client_bounds.bottom==monitor.rcWork.bottom,"maximized_custom_frame_respects_monitor_work_area");
        shell->ToggleMaximize();context->frame->Move(-16000,-16000);wxTheApp->Yield(true);
        context->frame->SetDisplayMode(0,0);context->frame->SetDisplayMode(1,1);shell->FitVideo();wxTheApp->Yield(true);
        context->videoController->JumpToFrame(50);
        context->frame->SetClientSize(FromDIP(wxSize(1480,900)));shell->SetView(0);context->frame->Layout();wxTheApp->Yield(true);int normal_video=context->videoDisplay->GetClientSize().y;shell->SetView(2);context->frame->Layout();wxTheApp->Yield(true);check(!context->frame->IsAudioShown()&&context->videoDisplay->GetClientSize().y>normal_video,"large_preview_view_makes_subtitles_larger_without_losing_editing_state");shell->SetView(1);check(!context->frame->IsVideoShown()&&context->frame->IsAudioShown(),"focus_timing_view_keeps_audio_and_hides_video");shell->SetView(0);
        for(int stage=0;stage<4;++stage){
            context->frame->SetClientSize(FromDIP(wxSize(1480,900)));context->frame->SendSizeEvent();ShowStage(stage);context->frame->Layout();Layout();
            Refresh();Update();wxTheApp->Yield(true);
            shell->FitVideo();context->frame->Layout();wxTheApp->Yield(true);
            check(shell->CurrentEditorFits(),"whole_window_current_line_editor_remains_visible");
            check(shell->TransportFits(),"all_playback_zoom_and_volume_controls_remain_visible");
            if(stage==0)for(auto name:{"import-online","import-offline","import-more"}){auto control=wxWindow::FindWindowByName(name,this);auto parent=control->GetParent();check(control->IsShownOnScreen()&&control->GetRect().GetBottom()<=parent->GetClientSize().y,"online_offline_and_more_import_paths_are_visible_on_the_first_screen");}
            if(stage==1)for(auto name:{"timing-listen-start","timing-listen-end","timing-confirm-next","timing-analyze"}){
                auto control=wxWindow::FindWindowByName(name,this);auto parent=control->GetParent();auto bounds=parent->GetClientSize();check(control->IsShownOnScreen()&&control->GetRect().GetBottom()<=bounds.y&&control->GetRect().GetRight()<=bounds.x,"primary_audition_confirm_and_analysis_controls_are_visible_without_scrolling");
            }
            check(save_button->GetLabel()==L"应用本行修改"&&save_button->GetClientSize().x>=GetClientSize().x-FromDIP(34),"save_caption_has_dedicated_full_width_row");
            auto size=GetClientSize();bool contained=true;
            for(auto control:stages)contained&=control->GetRect().GetRight()<=size.x;
            contained&=cancel_button->GetRect().GetBottom()<=size.y;
            contained&=save_button->GetRect().GetRight()<=size.x&&save_button->GetRect().GetBottom()<=size.y;
            check(contained,"workflow_navigation_and_task_footer_fit");
            wxBitmap bitmap(size.x,size.y);wxMemoryDC memory(bitmap);memory.SetBackground(*wxWHITE_BRUSH);memory.Clear();
            ::PrintWindow(static_cast<HWND>(GetHandle()),static_cast<HDC>(memory.GetHDC()),PW_CLIENTONLY|2);
            ::SendMessageW(static_cast<HWND>(GetHandle()),WM_PRINT,reinterpret_cast<WPARAM>(memory.GetHDC()),PRF_CLIENT|PRF_CHILDREN|PRF_ERASEBKGND|PRF_NONCLIENT);
            studio_ui::render_widgets(this,this,memory);
            if(stage==2&&units->GetNumberRows()>0){
                auto origin=ScreenToClient(units->ClientToScreen(wxPoint(0,0)));auto grid_size=units->GetClientSize();
                memory.SetClippingRegion(origin.x,origin.y,grid_size.x,grid_size.y);
                int width=units->GetRowLabelSize(),height=units->GetColLabelSize();for(int col=0;col<units->GetNumberCols();++col)width+=units->GetColSize(col);for(int row=0;row<units->GetNumberRows();++row)height+=units->GetRowSize(row);
                report["grid_dimensions"]=std::to_string(width)+" client="+std::to_string(grid_size.x)+" panel="+std::to_string(size.x);
                check(width<=grid_size.x,"workflow_all_unit_columns_visible");
                units->Render(memory,origin,wxSize(width,height));memory.DestroyClippingRegion();
            }
            memory.SelectObject(wxNullBitmap);
            auto rendered_image=bitmap.ConvertToImage();auto pixels=rendered_image.GetData();unsigned char lightest=0,darkest=255;
            for(int i=0;i<size.x*size.y*3;++i){lightest=std::max(lightest,pixels[i]);darkest=std::min(darkest,pixels[i]);}
            auto filename=folder/("workspace-stage-"+std::to_string(stage+1)+".png");
            check(rendered_image.SaveFile(wxString(filename.wstring()),wxBITMAP_TYPE_PNG)&&int(lightest)-int(darkest)>30,"workflow_page_has_actual_rendered_pixels");
            auto current_page=pages->GetCurrentPage();bool horizontal_fit=true;
            for(auto child:current_page->GetChildren())if(child->IsShown())horizontal_fit&=child->GetRect().GetRight()<=current_page->GetClientSize().x+1;
            check(horizontal_fit,"workflow_page_controls_fit_horizontal_viewport");
            auto frame_size=context->frame->GetClientSize();wxBitmap full(frame_size.x,frame_size.y);wxMemoryDC full_dc(full);full_dc.SetBackground(*wxWHITE_BRUSH);full_dc.Clear();
            ::PrintWindow(static_cast<HWND>(context->frame->GetHandle()),static_cast<HDC>(full_dc.GetHDC()),PW_CLIENTONLY|2);
            ::SendMessageW(static_cast<HWND>(context->frame->GetHandle()),WM_PRINT,reinterpret_cast<WPARAM>(full_dc.GetHDC()),PRF_CLIENT|PRF_CHILDREN|PRF_ERASEBKGND);
            studio_ui::render_widgets(context->frame,context->frame,full_dc);
            auto cards_origin=context->frame->ScreenToClient(shell->lyrics->ClientToScreen(wxPoint(0,0)));auto cards_size=shell->lyrics->GetClientSize();
            full_dc.SetDeviceOrigin(cards_origin.x,cards_origin.y);full_dc.SetClippingRegion(0,0,cards_size.x,cards_size.y);shell->lyrics->RenderCards(full_dc);full_dc.DestroyClippingRegion();full_dc.SetDeviceOrigin(0,0);
            auto panel_origin=context->frame->ScreenToClient(ClientToScreen(wxPoint(0,0)));full_dc.DrawBitmap(bitmap,panel_origin);
            // OpenGL cannot print to a GDI DC. Composite this same app's actual
            // subtitle renderer into the real native video viewport.
            auto display=context->videoDisplay;auto video_origin=context->frame->ScreenToClient(display->ClientToScreen(wxPoint(0,0)));auto video_size=display->GetClientSize();
            report["window_video_width"]=video_size.x;report["window_video_height"]=video_size.y;report["window_visible"]=context->frame->IsShownOnScreen();report["viewport_visible"]=display->IsShownOnScreen();report["video_mode"]=context->frame->IsVideoShown();report["video_provider_present"]=context->project->VideoProvider()!=nullptr;report["video_zoom"]=display->GetWindowZoom();
            check(video_size.x>100&&video_size.y>60,"whole_window_video_viewport_has_real_extent");
            if(video_size.x>0&&video_size.y>0){auto image=GetImage(*early).Scale(video_size.x,video_size.y,wxIMAGE_QUALITY_HIGH);full_dc.DrawBitmap(wxBitmap(image),video_origin);}
            auto audio_display=context->audioBox->StudioDisplay();auto audio_size=audio_display->GetClientSize();auto audio_origin=context->frame->ScreenToClient(audio_display->ClientToScreen(wxPoint(0,0)));
            wxBitmap audio_bitmap(audio_size.x,audio_size.y);{wxMemoryDC dc(audio_bitmap);dc.SetBackground(*wxWHITE_BRUSH);dc.Clear();audio_display->StudioRender(dc);}full_dc.DrawBitmap(audio_bitmap,audio_origin);
            auto split_area=context->karaoke->StudioSplitArea();auto split_size=split_area->GetClientSize();if(context->karaoke->IsShown()&&split_size.x>0&&split_size.y>0){wxBitmap split_bitmap(split_size.x,split_size.y);{wxMemoryDC dc(split_bitmap);context->karaoke->StudioRender(dc);}auto origin=context->frame->ScreenToClient(split_area->ClientToScreen(wxPoint(0,0)));full_dc.DrawBitmap(split_bitmap,origin);}
            full_dc.SelectObject(wxNullBitmap);auto whole_image=full.ConvertToImage();
            for(auto text:{L"歌词库",L"预览与校准",L"制作工具"}){
                auto label=wxWindow::FindWindowByName(wxString(L"studio-label:")+text,context->frame);check(label!=nullptr,"major_workspace_heading_exists");
                auto point=context->frame->ScreenToClient(label->ClientToScreen(wxPoint(0,0)));auto label_size=label->GetClientSize();auto colour=label->GetForegroundColour();int ink=0;
                for(int y=std::max(0,point.y);y<std::min(frame_size.y,point.y+label_size.y);++y)for(int x=std::max(0,point.x);x<std::min(frame_size.x,point.x+label_size.x);++x)
                    if(std::abs(int(whole_image.GetRed(x,y))-colour.Red())+std::abs(int(whole_image.GetGreen(x,y))-colour.Green())+std::abs(int(whole_image.GetBlue(x,y))-colour.Blue())<100)++ink;
                check(ink>15,"major_workspace_heading_has_visible_native_text");
            }
            check(whole_image.SaveFile(wxString((folder/("window-stage-"+std::to_string(stage+1)+".png")).wstring()),wxBITMAP_TYPE_PNG),"whole_window_self_render_saved");
            check(cards_origin.x>=0&&cards_origin.x+cards_size.x<frame_size.x&&video_origin.x+video_size.x<=panel_origin.x&&panel_origin.x+size.x<=frame_size.x,"whole_window_columns_do_not_overlap");
        }
        context->frame->SetClientSize(FromDIP(wxSize(1280,760)));context->frame->SendSizeEvent();ShowStage(2);context->frame->Layout();Layout();wxTheApp->Yield(true);
        check(save_button->GetRect().GetBottom()<=GetClientSize().y&&stages.back()->GetRect().GetRight()<=GetClientSize().x,"workflow_narrow_window_retains_navigation_and_save");
        bool narrow_fit=true;for(auto child:pages->GetCurrentPage()->GetChildren())if(child->IsShown())narrow_fit&=child->GetRect().GetRight()<=pages->GetCurrentPage()->GetClientSize().x+1;
        check(narrow_fit,"workflow_narrow_window_content_fits_width");
        shell->FitVideo();context->frame->Layout();wxTheApp->Yield(true);{auto mode=wxWindow::FindWindowByName("workspace-view",context->frame);auto panel=mode->GetParent();auto area=panel->GetParent();auto position=area->ScreenToClient(panel->ClientToScreen(wxPoint(0,0)));report["narrow_transport_geometry"]=std::to_string(position.x)+","+std::to_string(position.y)+" size="+std::to_string(panel->GetSize().x)+","+std::to_string(panel->GetSize().y)+" area="+std::to_string(area->GetClientSize().x)+","+std::to_string(area->GetClientSize().y);auto size=context->frame->GetClientSize();wxBitmap bitmap(size.x,size.y);{wxMemoryDC dc(bitmap);dc.Clear();::PrintWindow(static_cast<HWND>(context->frame->GetHandle()),static_cast<HDC>(dc.GetHDC()),PW_CLIENTONLY|2);::SendMessageW(static_cast<HWND>(context->frame->GetHandle()),WM_PRINT,reinterpret_cast<WPARAM>(dc.GetHDC()),PRF_CLIENT|PRF_CHILDREN|PRF_ERASEBKGND);studio_ui::render_widgets(context->frame,context->frame,dc);}bitmap.SaveFile(wxString((folder/"narrow-window.png").wstring()),wxBITMAP_TYPE_PNG);}check(shell->TransportFits(),"narrow_window_keeps_complete_transport_visible");
        ShowStage(0);context->frame->Layout();wxTheApp->Yield(true);for(auto name:{"import-add-media","import-paste-lyrics","import-online","import-offline","import-more"}){auto control=wxWindow::FindWindowByName(name,this);auto parent=control->GetParent();check(control->IsShownOnScreen()&&control->GetRect().GetBottom()<=parent->GetClientSize().y,"laptop_sized_import_page_keeps_every_starting_path_visible_without_scrolling");}ShowStage(2);context->frame->Layout();wxTheApp->Yield(true);
        auto luminance=[](wxColour const& colour){auto part=[](double value){value/=255;return value<=.04045?value/12.92:std::pow((value+.055)/1.055,2.4);};return .2126*part(colour.Red())+.7152*part(colour.Green())+.0722*part(colour.Blue());};
        for(bool enabled:{false,true}){
            save_button->Enable(enabled);auto palette=save_button->Palette(enabled);double a=luminance(palette.foreground),b=luminance(palette.background);
            check((std::max(a,b)+.05)/(std::min(a,b)+.05)>=4.5,"save_text_contrast_is_readable_enabled_and_disabled");
            for(double scale:{1.,1.5,2.}){
                auto original=save_button->GetClientSize();wxSize size(std::lround(original.x*scale),std::lround(original.y*scale));wxBitmap bitmap(size.x,size.y);
                wxRect caption;{wxMemoryDC dc(bitmap);save_button->Render(dc,size,scale);caption=save_button->CaptionBounds(dc,size,scale);}
                check(caption.x>=int(10*scale)&&caption.y>=int(4*scale)&&caption.GetRight()<size.x-int(10*scale)&&caption.GetBottom()<size.y-int(4*scale),"complete_chinese_save_caption_fits_scaled_render");
                auto image=bitmap.ConvertToImage();int foreground=0;
                for(int y=std::max(0,caption.y);y<std::min(size.y,caption.GetBottom()+1);++y)for(int x=std::max(0,caption.x);x<std::min(size.x,caption.GetRight()+1);++x)
                    if(std::abs(int(image.GetRed(x,y))-palette.foreground.Red())+std::abs(int(image.GetGreen(x,y))-palette.foreground.Green())+std::abs(int(image.GetBlue(x,y))-palette.foreground.Blue())<80)++foreground;
                check(foreground>25,"chinese_save_caption_has_actual_visible_ink");
                check(image.SaveFile(wxString((folder/("save-caption-"+std::string(enabled?"enabled-":"disabled-")+std::to_string(int(scale*100))+".png")).wstring()),wxBITMAP_TYPE_PNG),"save_caption_state_render_saved");
            }
        }
        UpdateOverview();
#if wxUSE_ACCESSIBILITY
        wxString accessible_name;wxAccRole accessible_role;
        auto accessible=save_button->GetOrCreateAccessible();check(accessible&&accessible->GetName(0,&accessible_name)==wxACC_OK&&accessible_name==L"应用本行修改"&&accessible->GetRole(0,&accessible_role)==wxACC_OK&&accessible_role==wxROLE_SYSTEM_PUSHBUTTON,"save_control_retains_accessible_name_and_button_role");
#endif
#endif
        auto drag_project=studio_workflow::copy(project);auto& drag_object=static_cast<json::Object&>(drag_project);drag_object["media"]="test-video.mp4";drag_object["video"]="test-video.mp4";
        auto retained_history=context->ass->GetScriptInfo("Shengao API History");if(!retained_history.empty())drag_object["api_history"]=parsed(std::string(retained_history));
        {std::ofstream output(folder/"drag-project.json");agi::JsonWriter::Write(drag_project,output);}
        context->subsController->Save(agi::fs::path((folder/"before-json.ass").wstring()),"UTF-8");
        wxArrayString json_names;json_names.Add(wxString((folder/"drag-project.json").wstring()));drop->OnDropFiles(0,0,json_names);
        for(int attempt=0;attempt<100&&context->ass->Events.size()!=1;++attempt){wxTheApp->ProcessPendingEvents();wxMilliSleep(10);}
        auto json_line=context->selectionController->GetActiveLine();
        check(context->ass->Events.size()==1&&json_line&&field(ReadLine(json_line),"text")==field(fixture,"text")&&field(ReadLine(json_line),"kana")==field(fixture,"kana"),"json_drop_uses_validated_project_open");
        check(context->project->VideoProvider()&&context->project->AudioProvider()&&!context->ass->GetScriptInfo("Shengao API History").empty(),"json_drop_restores_relative_media_and_api_history");
        report["ok"]=true;
    }catch(std::exception const& e){report["ok"]=false;report["error"]=e.what();}
    catch(...){report["ok"]=false;report["error"]="Unknown native integration failure";}
    report["passed"]=std::move(passed);
    try{report["document"]=ReadLines(false);}catch(...){}
    std::ofstream output(folder/"native-report.json",std::ios::binary);agi::JsonWriter::Write(report,output);
}
