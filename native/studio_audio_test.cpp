// Copyright (c) 2026 Shengao Karaoke Studio contributors. MIT.
#include <gtest/gtest.h>
#include "studio_audio_provider.h"
#include <cstdint>

namespace {
class TestAudio final : public agi::AudioProvider {
    void FillBuffer(void *buffer,int64_t start,int64_t count) const override {
        auto samples=static_cast<int16_t*>(buffer);
        for(int64_t i=0;i<count;++i)samples[i]=static_cast<int16_t>(start+i);
    }
public:
    TestAudio(){channels=1;sample_rate=48000;bytes_per_sample=2;num_samples=480000;decoded_samples=480000;}
};
}

TEST(studio_playback, half_speed_keeps_original_sample_coordinates) {
    TestAudio source;StudioRateProvider playback(&source,.5);
    EXPECT_EQ(playback.GetSampleRate(),24000);
    EXPECT_EQ(playback.GetNumSamples(),source.GetNumSamples());
    int16_t samples[4]={};playback.GetAudio(samples,1234,4);
    EXPECT_EQ(samples[0],1234);EXPECT_EQ(samples[3],1237);
    EXPECT_EQ(playback.GetChannels(),1);EXPECT_EQ(playback.GetBytesPerSample(),2);
}

TEST(studio_playback, normal_speed_preserves_rate) {
    TestAudio source;StudioRateProvider playback(&source,1.0);
    EXPECT_EQ(playback.GetSampleRate(),48000);
}
