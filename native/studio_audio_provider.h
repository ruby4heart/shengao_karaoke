// Copyright (c) 2026 Shengao Karaoke Studio contributors. MIT.
#pragma once
#include <libaegisub/audio/provider.h>
#include <algorithm>
#include <cmath>

// Playback-only view: original sample indices remain the time-axis coordinate.
// Changing the advertised sample rate deliberately changes pitch as well as speed.
class StudioRateProvider final : public agi::AudioProvider {
    agi::AudioProvider *source;
    void FillBuffer(void *buffer,int64_t start,int64_t count) const override {
        source->GetAudio(buffer,start,count);
    }
public:
    StudioRateProvider(agi::AudioProvider *source,double rate):source(source) {
        channels=source->GetChannels();num_samples=source->GetNumSamples();
        decoded_samples=source->GetDecodedSamples();bytes_per_sample=source->GetBytesPerSample();
        float_samples=source->AreSamplesFloat();
        sample_rate=std::max(1000,int(std::lround(source->GetSampleRate()*rate)));
    }
};
