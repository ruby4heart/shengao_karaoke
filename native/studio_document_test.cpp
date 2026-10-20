// Copyright (c) 2026 Shengao Karaoke Studio contributors. MIT.
#include <gtest/gtest.h>
#include <libaegisub/json.h>
#include "studio_document.h"
#include <sstream>

namespace {
json::UnknownElement line(std::string const& input) {
    std::istringstream stream(input);return agi::json_util::parse(stream);
}
}
TEST(studio_document, rejects_sub_centisecond_overlap_before_mutating_document) {
    auto value=line(R"({"text":"ab","start":0,"end":1000,"units":[{"text":"a","start":0,"end":503},{"text":"b","start":502,"end":1000}]})");
    EXPECT_THROW(studio_document::karaoke(value),std::runtime_error);
}
TEST(studio_document, preserves_silent_gaps_and_source_text) {
    auto value=line(R"({"text":"歌う","start":1000,"end":3000,"units":[{"text":"歌","start":1200,"end":1800},{"text":"う","start":2100,"end":3000}]})");
    EXPECT_EQ(studio_document::karaoke(value),"{\\k20}{\\kf60}歌{\\k30}{\\kf90}う");
}
TEST(studio_document, supports_one_kanji_group_with_multiple_sung_mora) {
    auto value=line(R"({"text":"今日","start":0,"end":2000,"units":[{"text":"今日","start":0,"end":2000,"kana":"きょう","highlights":[{"kana":"きょ","start":0,"end":800},{"kana":"う","start":800,"end":2000}]}]})");
    EXPECT_EQ(studio_document::karaoke(value),"{\\kf80}今日|!きょ{\\kf120}#|う");
}
TEST(studio_document, refuses_incomplete_or_changed_source_lyrics) {
    auto value=line(R"({"text":"歌う","start":0,"end":1000,"units":[{"text":"歌","start":0,"end":1000}]})");
    EXPECT_THROW(studio_document::karaoke(value),std::runtime_error);
}
TEST(studio_document, decodes_ass_line_breaks_and_non_breaking_space) {
    EXPECT_EQ(studio_document::plain("今日\\N歌う\\n空\\hへ"),"今日\n歌う\n空\xC2\xA0へ");
    EXPECT_EQ(studio_document::literal(studio_document::plain("歌\\N空")),"歌\\N空");
}
TEST(studio_document, rejects_invalid_matching_metadata) {
    auto bad=line(R"({"text":"歌","start":0,"end":1000,"units":[],"match":{"status":"matched","score":2}})");
    EXPECT_THROW(studio_document::karaoke(bad),std::runtime_error);
    auto good=line(R"({"text":"歌","start":0,"end":1000,"units":[],"match":{"status":"uncertain","score":0.6,"coverage":1}})");
    EXPECT_EQ(studio_document::karaoke(good),"歌");
}
