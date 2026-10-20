// Copyright (c) 2026 Shengao Karaoke Studio contributors. MIT.
#include <gtest/gtest.h>
#include "studio_workflow.h"
#include "studio_editing.h"
#include "studio_karaoke.h"
#include "studio_calibration.h"
#include "studio_pauses.h"

namespace {
void syllables(agi::ass::Karaoke& karaoke,std::vector<std::pair<std::string,int>> const& parts) {
    std::vector<agi::ass::KaraokeSyllable> result;int cursor=1000;
    for (auto const& [text,duration]:parts) {result.push_back({cursor,duration,text,"\\kf",{}});cursor+=duration;}
    karaoke.SetLine(std::move(result),false,std::nullopt);
}
json::UnknownElement parse(std::string const& text){std::istringstream in(text);return agi::json_util::parse(in);}
auto const& object(json::UnknownElement const& value){return static_cast<json::Object const&>(value);}
int time(json::UnknownElement const& value,char const *key){return studio_document::time(object(value),key);}
json::UnknownElement sample(){return parse(R"({"id":"1","text":"今日","start":1000,"end":3000,"reviewed":true,"locked":true,"units":[{"text":"今日","kana":"きょう","start":1200,"end":2800,"locked":true,"source":"manual","highlights":[{"kana":"きょ","start":1200,"end":1800,"source":"manual"},{"kana":"う","start":2100,"end":2800,"source":"manual"}]}]})");}
}
TEST(studio_karaoke, word_boundaries_ignore_asr_pauses_without_changing_times) {
    agi::ass::Karaoke karaoke;
    syllables(karaoke,{{"真夜中",400},{"の",100},{"",20},{"",30},{"ネオンサイン",1000},{"が",100},{"",1500},{"君",300},{"を",100},{"抱きしめ",500},{"",50},{"て",100}});
    auto before=karaoke.GetText();auto visible=studio_karaoke::visible_syllables(karaoke);
    EXPECT_EQ(visible,(std::vector<size_t>{0,1,4,5,7,8,9,11}));
    EXPECT_EQ(karaoke.GetText(),before);EXPECT_EQ((karaoke.begin()+7)->start_time,4150);
}
TEST(studio_karaoke, whitespace_has_no_own_cell_and_exact_original_text_survives) {
    agi::ass::Karaoke karaoke;
    syllables(karaoke,{{"",100},{" 　",100},{"今日",300},{" ",80},{"\\h\\N",30},{"も",100},{"　",50},{"",100}});
    auto before=karaoke.GetText();EXPECT_EQ(studio_karaoke::visible_syllables(karaoke),(std::vector<size_t>{2,5}));
    EXPECT_EQ(karaoke.GetText(),before);
    for (auto text:{"","\t \r\n","　","\xC2\xA0","\xE2\x80\x8B","\\h\\N\\n"}) EXPECT_TRUE(studio_karaoke::blank(text));
    for (auto text:{"歌","。","#|う"," 歌 ","\\hello"}) EXPECT_FALSE(studio_karaoke::blank(text));
}
TEST(studio_karaoke, all_silence_has_no_phantom_word) {
    agi::ass::Karaoke karaoke;syllables(karaoke,{{"",300},{"　",100},{"",0}});
    EXPECT_TRUE(studio_karaoke::visible_syllables(karaoke).empty());
    EXPECT_FALSE(studio_karaoke::remove_boundary(karaoke,{},0));EXPECT_EQ(karaoke.size(),3u);
}
TEST(studio_karaoke, one_click_removes_word_boundary_across_multiple_gaps_and_keeps_tags) {
    agi::ass::Karaoke karaoke;syllables(karaoke,{{"",100},{"今日",500},{"",50},{" ",70},{"",300},{"も",200},{"歌う",400}});
    std::vector<agi::ass::KaraokeSyllable> styled(karaoke.begin(),karaoke.end());styled[2].ovr_tags[0]="{\\bord3}";styled[5].ovr_tags[0]="{\\i1}";karaoke.SetLine(std::move(styled),false,std::nullopt);
    auto visible=studio_karaoke::visible_syllables(karaoke);EXPECT_TRUE(studio_karaoke::remove_boundary(karaoke,visible,1));
    ASSERT_EQ(karaoke.size(),3u);auto const& joined=*(karaoke.begin()+1);
    EXPECT_EQ(joined.text,"今日 も");EXPECT_EQ(joined.start_time,1100);EXPECT_EQ(joined.duration,1120);
    EXPECT_EQ(joined.GetText(false),"今日{\\bord3} {\\i1}も");
    EXPECT_EQ(karaoke.begin()->duration,100);EXPECT_EQ((karaoke.begin()+2)->start_time,2220);
}
TEST(studio_karaoke, split_inside_word_after_gap_targets_original_syllable) {
    agi::ass::Karaoke karaoke;syllables(karaoke,{{"の",100},{"",90},{"ネオンサイン",600}});
    auto visible=studio_karaoke::visible_syllables(karaoke);ASSERT_EQ(visible.size(),2u);
    size_t target=visible[1];ASSERT_TRUE(studio_karaoke::can_split((karaoke.begin()+target)->text,9));
    karaoke.AddSplit(target,9);ASSERT_EQ(karaoke.size(),4u);
    EXPECT_EQ((karaoke.begin()+1)->duration,90);EXPECT_EQ((karaoke.begin()+2)->text,"ネオン");EXPECT_EQ((karaoke.begin()+3)->text,"サイン");
}
TEST(studio_karaoke, joining_empty_runs_preserves_multiple_styles_at_the_same_text_offset) {
    agi::ass::Karaoke karaoke;syllables(karaoke,{{"今日",500},{"",20},{"",30},{"も",100}});
    std::vector<agi::ass::KaraokeSyllable> styled(karaoke.begin(),karaoke.end());
    styled[0].ovr_tags[6]="{\\bord3}";styled[1].ovr_tags[0]="{\\i1}";styled[2].ovr_tags[0]="{\\c&HFF00&}";styled[3].ovr_tags[0]="{\\u1}";
    karaoke.SetLine(std::move(styled),false,std::nullopt);
    int notifications=0;auto connection=karaoke.AddSyllablesChangedListener([&]{++notifications;});
    EXPECT_TRUE(studio_karaoke::remove_boundary(karaoke,studio_karaoke::visible_syllables(karaoke),1));
    ASSERT_EQ(karaoke.size(),1u);EXPECT_EQ(karaoke.begin()->duration,650);
    EXPECT_EQ(karaoke.begin()->GetText(false),"今日{\\bord3}{\\i1}{\\c&HFF00&}{\\u1}も");
    EXPECT_EQ(notifications,1);
}
TEST(studio_karaoke, clicks_at_text_edges_do_not_create_empty_or_whitespace_syllables) {
    for (size_t byte:{0u,1u,2u,3u,5u,6u,7u,8u,9u}) EXPECT_FALSE(studio_karaoke::can_split(" 歌う ",byte));
    EXPECT_TRUE(studio_karaoke::can_split(" 歌う ",4));
    EXPECT_FALSE(studio_karaoke::can_split("歌　",3));EXPECT_FALSE(studio_karaoke::can_split("　歌",3));
    EXPECT_FALSE(studio_karaoke::can_split("",0));
}
TEST(studio_calibration, word_time_changes_are_rounded_and_do_not_touch_other_words) {
    auto value=parse(R"({"text":"歌う","start":1000,"end":3000,"units":[{"text":"歌","start":1000,"end":1800},{"text":"う","start":2000,"end":3000}]})");
    auto adjusted=studio_calibration::timed(value,0,1103,1907);auto const& units=static_cast<json::Array const&>(object(adjusted).at("units"));
    EXPECT_EQ(time(units[0],"start"),1100);EXPECT_EQ(time(units[0],"end"),1910);EXPECT_EQ(time(units[1],"start"),2000);
    EXPECT_EQ(time(value,"start"),1000);EXPECT_THROW(studio_calibration::timed(value,0,1000,2100),std::runtime_error);
}
TEST(studio_calibration, line_endpoints_preserve_middle_word_edges_and_readings) {
    auto value=parse(R"({"text":"今日も歌う","start":1000,"end":4000,"units":[{"text":"今日","kana":"きょう","start":1000,"end":2000},{"text":"も","start":2000,"end":2500},{"text":"歌う","start":2500,"end":4000}]})");
    auto adjusted=studio_calibration::timed(value,-1,900,4200);auto const& units=static_cast<json::Array const&>(object(adjusted).at("units"));
    EXPECT_EQ(time(units[0],"start"),900);EXPECT_EQ(time(units[0],"end"),2000);EXPECT_EQ(time(units[1],"end"),2500);EXPECT_EQ(time(units[2],"end"),4200);
    EXPECT_THROW(studio_calibration::timed(value,-1,2100,4200),std::runtime_error);
}
TEST(studio_calibration, moving_a_word_preserves_mora_pauses_and_reading_protection) {
    auto value=sample();auto adjusted=studio_calibration::timed(value,0,1400,3000);auto const& units=static_cast<json::Array const&>(object(adjusted).at("units"));
    auto const& parts=static_cast<json::Array const&>(object(units[0]).at("highlights"));
    EXPECT_EQ(time(parts[0],"start"),1400);EXPECT_EQ(time(parts[1],"start"),2300);EXPECT_EQ(time(parts[1],"end"),3000);
    EXPECT_TRUE(static_cast<json::Boolean const&>(object(units[0]).at("locked")));EXPECT_FALSE(static_cast<json::Boolean const&>(object(adjusted).at("reviewed")));
}
TEST(studio_calibration, confirmation_marks_timing_as_manual_but_keeps_text) {
    auto value=sample();auto adjusted=studio_calibration::confirmed(value);EXPECT_TRUE(static_cast<json::Boolean const&>(object(adjusted).at("reviewed")));
    EXPECT_EQ(studio_document::text(object(adjusted),"text"),"今日");EXPECT_EQ(time(adjusted,"start"),1000);
}
TEST(studio_karaoke, timing_and_reading_changes_preserve_original_style_tags) {
    std::vector<agi::ass::KaraokeSyllable> old{{1000,500,"今日","\\kf",{{0,"{\\bord3}"},{6,"{\\i1}"}}},{1500,200,"も","\\kf",{{0,"{\\u1}"}}}};
    std::vector<agi::ass::KaraokeSyllable> after{{1000,300,"今日|!きょ","\\kf",{}},{1300,500,"#|う","\\kf",{}},{1800,200,"も|!も","\\kf",{}}};
    studio_karaoke::preserve_tags(old,after);std::string result;for(auto const& part:after)result+=part.GetText(true);
    EXPECT_NE(result.find("{\\bord3}"),std::string::npos);EXPECT_NE(result.find("{\\i1}"),std::string::npos);EXPECT_NE(result.find("{\\u1}"),std::string::npos);
    EXPECT_EQ(after[0].duration,300);EXPECT_EQ(after[2].text,"も|!も");
}
TEST(studio_karaoke, furigana_markup_cannot_be_split_into_corrupted_lyrics) {
    agi::ass::Karaoke karaoke;syllables(karaoke,{{"今日|!きょ",500},{"#|う",300}});auto before=karaoke.GetText();
    EXPECT_EQ(studio_karaoke::display_text("今日|!きょ"),"今日〔きょ〕");EXPECT_EQ(studio_karaoke::display_text("#|う"),"う");
    EXPECT_FALSE(studio_karaoke::can_split("今日|!きょ",3));EXPECT_FALSE(studio_karaoke::remove_boundary(karaoke,studio_karaoke::visible_syllables(karaoke),1));EXPECT_EQ(karaoke.GetText(),before);
}
TEST(studio_calibration, adjacent_word_edges_move_together_and_inner_manual_morae_stay_fixed) {
    auto value=parse(R"({"text":"今日も","start":1000,"end":4000,"units":[{"text":"今日","kana":"きょう","start":1000,"end":3000,"highlights":[{"kana":"きょ","start":1000,"end":1800,"source":"manual"},{"kana":"う","start":1800,"end":3000,"source":"manual"}]},{"text":"も","start":3000,"end":4000}]})");
    auto adjusted=studio_calibration::timed(value,0,900,3100);auto const& units=static_cast<json::Array const&>(object(adjusted).at("units"));auto const& parts=static_cast<json::Array const&>(object(units[0]).at("highlights"));
    EXPECT_EQ(time(adjusted,"start"),900);EXPECT_EQ(time(units[1],"start"),3100);EXPECT_EQ(time(parts[0],"end"),1800);EXPECT_EQ(time(parts[1],"start"),1800);
}
TEST(studio_workflow, legacy_history_matches_empty_optional_reading_fields) {
    auto value=sample();auto changed=studio_workflow::copy(value);auto& row=static_cast<json::Object&>(changed);row["reading_review"]=json::Object();auto& word=static_cast<json::Object&>(static_cast<json::Array&>(row.at("units"))[0]);word["reading_source"]="";
    EXPECT_EQ(studio_workflow::canonical(value),studio_workflow::canonical(changed));word["reading_source"]="manual";EXPECT_NE(studio_workflow::canonical(value),studio_workflow::canonical(changed));
}
TEST(studio_workflow, old_projects_with_kanji_in_kana_are_flagged_for_reading_review) {
    json::Array lines;lines.emplace_back(parse(R"({"id":"1","text":"今日","kana":"今日","start":0,"end":1000,"units":[{"text":"今日","kana":"今日","start":0,"end":1000}]})"));
    auto issues=studio_workflow::inspect(lines);EXPECT_TRUE(std::any_of(issues.begin(),issues.end(),[](auto const& item){return item.code=="reading"&&item.message.find("含有汉字")!=std::string::npos;}));
}
TEST(studio_workflow, lrc_handles_multiple_tags_sorting_fraction_and_global_offset){
    auto result=studio_workflow::lrc("[ti:Test]\n[00:03.5]歌う\n[00:01.20][00:07.123]今日\n[offset:-100]\n");
    ASSERT_EQ(result.size(),3u);EXPECT_EQ(time(result[0],"start"),1100);EXPECT_EQ(time(result[0],"end"),3400);EXPECT_EQ(time(result[2],"start"),7023);EXPECT_EQ(studio_document::text(object(result[0]),"text"),"今日");
}
TEST(studio_workflow, lrc_blank_timestamp_ends_previous_lyric_and_media_bounds_last_line){
    auto result=studio_workflow::lrc("[00:01]歌\n[00:02]\n[00:03]空\n",4000);
    ASSERT_EQ(result.size(),2u);EXPECT_EQ(time(result[0],"end"),2000);EXPECT_EQ(time(result[1],"end"),4000);
}
TEST(studio_workflow, invalid_lrc_and_negative_offsets_are_rejected){
    EXPECT_THROW(studio_workflow::lrc("[00:90]歌"),std::runtime_error);
    EXPECT_THROW(studio_workflow::lrc("[00:01]歌\n[offset:-2000]"),std::runtime_error);
    EXPECT_THROW(studio_workflow::lrc("[00:01]歌\n[00:xx]空"),std::runtime_error);
    EXPECT_THROW(studio_workflow::lrc("[00:01]<00:01.00>歌"),std::runtime_error);
    EXPECT_THROW(studio_workflow::lrc("[00:05]歌",3000),std::runtime_error);
}
TEST(studio_workflow, offset_moves_all_boundaries_preserving_silence_and_protection){
    auto value=sample();auto shifted=studio_workflow::shifted(value,250);
    EXPECT_EQ(time(value,"start"),1000);EXPECT_EQ(time(shifted,"start"),1250);
    auto const& unit=static_cast<json::Array const&>(object(shifted).at("units")).front();
    auto const& parts=static_cast<json::Array const&>(object(unit).at("highlights"));
    EXPECT_EQ(time(unit,"start"),1450);EXPECT_EQ(time(parts[1],"start")-time(parts[0],"end"),300);
    EXPECT_TRUE(static_cast<json::Boolean const&>(object(shifted).at("locked")));
    EXPECT_TRUE(static_cast<json::Boolean const&>(object(unit).at("locked")));
    EXPECT_FALSE(static_cast<json::Boolean const&>(object(shifted).at("reviewed")));
    EXPECT_THROW(studio_workflow::shifted(value,-2000),std::runtime_error);
}
TEST(studio_workflow, metadata_edits_have_identical_ass_shape_but_reading_splits_do_not){
    auto first=sample();auto second=studio_workflow::copy(first);auto& line=static_cast<json::Object&>(second);line["translation"]="new";line["romaji"]="kyou";line["reviewed"]=false;
    static_cast<json::Object&>(static_cast<json::Array&>(line.at("units"))[0])["reading_source"]="manual";
    EXPECT_EQ(studio_workflow::shape(first),studio_workflow::shape(second));
    auto& unit=static_cast<json::Object&>(static_cast<json::Array&>(line.at("units")).front());
    auto& highlights=static_cast<json::Array&>(unit.at("highlights"));static_cast<json::Object&>(highlights[0])["kana"]="き";static_cast<json::Object&>(highlights[1])["kana"]="ょう";
    EXPECT_NE(studio_workflow::shape(first),studio_workflow::shape(second));
}
TEST(studio_workflow, global_offset_does_not_promote_estimates_to_verified_timing){
    auto value=sample();auto& unit=static_cast<json::Object&>(static_cast<json::Array&>(static_cast<json::Object&>(value).at("units")).front());unit["source"]="estimated";
    auto& part=static_cast<json::Object&>(static_cast<json::Array&>(unit.at("highlights")).front());part["source"]="estimated";
    auto shifted=studio_workflow::shifted(value,200);auto const& moved=static_cast<json::Object const&>(static_cast<json::Array const&>(object(shifted).at("units")).front());
    EXPECT_EQ(studio_document::text(moved,"source"),"estimated");
    EXPECT_EQ(studio_document::text(object(static_cast<json::Array const&>(moved.at("highlights")).front()),"source"),"estimated");
}
TEST(studio_workflow, history_matching_ignores_only_ephemeral_ids){
    auto first=sample();auto second=studio_workflow::copy(first);static_cast<json::Object&>(second)["id"]="999";
    EXPECT_EQ(studio_workflow::canonical(first),studio_workflow::canonical(second));
    static_cast<json::Object&>(second)["translation"]="manual change";
    EXPECT_NE(studio_workflow::canonical(first),studio_workflow::canonical(second));
}
TEST(studio_workflow, checks_detect_estimates_missing_readings_zero_duration_and_overlap){
    auto first=parse(R"({"id":"1","text":"歌","start":0,"end":2000,"units":[{"text":"歌","kana":"","start":0,"end":0,"source":"estimated"}]})");
    auto second=parse(R"({"id":"2","text":"空","start":1000,"end":3000,"units":[]})");
    json::Array lines;lines.emplace_back(std::move(first));lines.emplace_back(std::move(second));auto report=studio_workflow::inspect(lines);
    for(auto code:{"timing","reading","review","overlap"})EXPECT_TRUE(std::any_of(report.begin(),report.end(),[&](auto const& item){return item.code==code;}));
    EXPECT_FALSE(std::any_of(report.begin(),report.end(),[](auto const& item){return item.error;}));
}
TEST(studio_workflow, checks_distinguish_invalid_data_from_editable_warnings){
    json::Array lines;lines.emplace_back(parse(R"({"id":"bad","text":"歌","start":500,"end":100,"units":[]})"));
    auto report=studio_workflow::inspect(lines);ASSERT_EQ(report.size(),1u);EXPECT_TRUE(report.front().error);EXPECT_EQ(report.front().code,"invalid");
}
TEST(studio_editing, manual_split_preserves_source_text_and_protection){
    auto value=sample();auto split=studio_editing::split(value,0,{"今","日"},{"きょ","う"});
    auto const& units=static_cast<json::Array const&>(object(split).at("units"));ASSERT_EQ(units.size(),2u);
    EXPECT_EQ(studio_document::text(object(split),"text"),"今日");EXPECT_EQ(time(units.front(),"start"),1200);EXPECT_EQ(time(units.back(),"end"),2800);
    EXPECT_TRUE(static_cast<json::Boolean const&>(object(units.front()).at("locked")));
    EXPECT_FALSE(static_cast<json::Boolean const&>(object(split).at("reviewed")));
    EXPECT_THROW(studio_editing::split(value,0,{"今 ","日"}),std::runtime_error);
    EXPECT_THROW(studio_editing::split(value,0,{"今","日"},{"きょう"}),std::runtime_error);
    EXPECT_EQ(studio_document::text(object(value),"text"),"今日");
}
TEST(studio_editing, merging_keeps_existing_morae_and_silence){
    auto value=parse(R"({"text":"今日も","start":1000,"end":4000,"units":[{"text":"今日","kana":"きょう","romaji":"kyou","start":1000,"end":3000,"source":"manual","highlights":[{"kana":"きょ","start":1000,"end":1800,"source":"manual"},{"kana":"う","start":2000,"end":3000,"source":"manual"}]},{"text":"も","kana":"も","romaji":"mo","start":3300,"end":4000,"source":"matched","locked":true}]})");
    auto result=studio_editing::merge(value,0);auto const& units=static_cast<json::Array const&>(object(result).at("units"));ASSERT_EQ(units.size(),1u);
    auto const& parts=static_cast<json::Array const&>(object(units.front()).at("highlights"));ASSERT_EQ(parts.size(),3u);EXPECT_EQ(time(parts[1],"start"),2000);EXPECT_EQ(time(parts[2],"start"),3300);
    EXPECT_TRUE(static_cast<json::Boolean const&>(object(units.front()).at("locked")));EXPECT_EQ(studio_document::text(object(units.front()),"romaji"),"kyou mo");
    EXPECT_THROW(studio_editing::merge(value,1),std::runtime_error);
}
TEST(studio_editing, choosing_chorus_candidate_does_not_replace_lyrics){
    auto value=sample();static_cast<json::Object&>(value)["match"]=parse(R"({"status":"uncertain","score":1,"coverage":1})");
    auto alternative=parse(R"({"start":10000,"end":12000,"units":[{"text":"今日","kana":"きょう","romaji":"kyou","start":10000,"end":12000,"source":"estimated"}],"score":1,"coverage":1,"recognized":"今日","method":"text"})");
    auto chosen=studio_editing::candidate(value,alternative);EXPECT_EQ(time(chosen,"start"),10000);EXPECT_EQ(studio_document::text(object(chosen),"text"),"今日");EXPECT_EQ(studio_document::text(object(object(chosen).at("match")),"status"),"manual");
    static_cast<json::Object&>(alternative)["units"]=parse(R"([{"text":"今 日","kana":"きょう","start":10000,"end":12000}])");
    EXPECT_THROW(studio_editing::candidate(value,alternative),std::runtime_error);
}

namespace {
json::UnknownElement pause_sample(){return parse(R"({"text":"今日も","start":1000,"end":5000,"reviewed":true,"units":[{"text":"今日","kana":"きょう","start":1100,"end":3000,"source":"manual","highlights":[{"kana":"きょ","start":1100,"end":1800,"source":"manual"},{"kana":"う","start":2000,"end":2800,"source":"manual"}]},{"text":"も","kana":"も","start":3300,"end":4700,"source":"manual"}]})");}
}
TEST(studio_pauses, enumerate_word_and_mora_gaps_with_optional_edges){
    auto line=pause_sample();auto gaps=studio_pauses::gaps(line);ASSERT_EQ(gaps.size(),2u);
    EXPECT_EQ(gaps[0].start,1800);EXPECT_EQ(gaps[0].end,2000);EXPECT_EQ(gaps[1].start,2800);EXPECT_EQ(gaps[1].end,3300);
    EXPECT_EQ(studio_pauses::gaps(line,true).size(),4u);
    EXPECT_TRUE(studio_pauses::gaps(parse(R"({"text":"歌","start":0,"end":1000,"units":[]})")).empty());
}
TEST(studio_pauses, preserve_and_cancel_are_exact_and_do_not_reconfirm){
    auto line=pause_sample();auto before=studio_workflow::encode(line);
    EXPECT_EQ(studio_workflow::encode(studio_pauses::apply(line,0,{0,1})),before);
    EXPECT_EQ(studio_workflow::encode(studio_pauses::apply(line,1,{})),before);
}
TEST(studio_pauses, merge_previous_covers_word_margin_without_crossing_next_word){
    auto line=pause_sample();auto result=studio_pauses::apply(line,1,{1});
    auto const& units=static_cast<json::Array const&>(object(result).at("units"));auto const& parts=static_cast<json::Array const&>(object(units[0]).at("highlights"));
    EXPECT_EQ(time(parts[1],"end"),3300);EXPECT_EQ(time(units[0],"end"),3300);EXPECT_EQ(time(units[1],"start"),3300);
    EXPECT_EQ(studio_pauses::gaps(result).size(),1u);EXPECT_EQ(time(result,"start"),1000);EXPECT_EQ(time(result,"end"),5000);
    EXPECT_EQ(studio_document::text(object(result),"text"),"今日も");EXPECT_FALSE(static_cast<json::Boolean const&>(object(result).at("reviewed")));
    EXPECT_EQ(studio_pauses::gaps(line).size(),2u);
}
TEST(studio_pauses, merge_next_starts_next_mora_early_without_changing_other_gaps){
    auto result=studio_pauses::apply(pause_sample(),2,{0});auto const& units=static_cast<json::Array const&>(object(result).at("units"));auto const& parts=static_cast<json::Array const&>(object(units[0]).at("highlights"));
    EXPECT_EQ(time(parts[0],"end"),1800);EXPECT_EQ(time(parts[1],"start"),1800);EXPECT_EQ(time(units[1],"start"),3300);
    EXPECT_EQ(studio_document::text(object(units[0]),"kana"),"きょう");EXPECT_EQ(studio_pauses::gaps(result).size(),1u);
}
TEST(studio_pauses, selected_edges_extend_real_lyrics_without_changing_line_limits){
    auto result=studio_pauses::apply(pause_sample(),2,{0,3},true);auto const& units=static_cast<json::Array const&>(object(result).at("units"));
    EXPECT_EQ(time(units[0],"start"),1000);EXPECT_EQ(time(units[1],"end"),5000);EXPECT_EQ(studio_pauses::gaps(result,true).size(),2u);
}
TEST(studio_pauses, locks_and_invalid_selection_cannot_modify_data){
    auto line=pause_sample();static_cast<json::Object&>(line)["locked"]=true;
    EXPECT_THROW(studio_pauses::apply(line,1,{0}),std::runtime_error);
    EXPECT_NO_THROW(studio_pauses::apply(line,0,{0}));
    EXPECT_THROW(studio_pauses::apply(pause_sample(),1,{99}),std::runtime_error);
    EXPECT_THROW(studio_pauses::apply(pause_sample(),3,{0}),std::runtime_error);
}

TEST(studio_guidance, punctuation_and_spaces_cannot_trap_next_step_in_mora_generation){
    for(auto kana:{"", " ", "、", "。", "!"}){auto value=parse(R"({"text":"。","start":0,"end":100,"kana":""})");static_cast<json::Object&>(value)["kana"]=kana;EXPECT_FALSE(studio_workflow::needs_mora(value));}
    auto word=parse(R"({"text":"今日","start":0,"end":1000,"kana":"きょう"})");EXPECT_TRUE(studio_workflow::needs_mora(word));static_cast<json::Object&>(word)["highlights"]=parse(R"([{"kana":"きょう","start":0,"end":1000}])");EXPECT_FALSE(studio_workflow::needs_mora(word));
}
