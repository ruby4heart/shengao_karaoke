// Copyright (c) 2005, Niels Martin Hansen, Rodrigo Braz Monteiro
// All rights reserved.
//
// Redistribution and use in source and binary forms, with or without
// modification, are permitted provided that the following conditions are met:
//
//   * Redistributions of source code must retain the above copyright notice,
//     this list of conditions and the following disclaimer.
//   * Redistributions in binary form must reproduce the above copyright notice,
//     this list of conditions and the following disclaimer in the documentation
//     and/or other materials provided with the distribution.
//   * Neither the name of the Aegisub Group nor the names of its contributors
//     may be used to endorse or promote products derived from this software
//     without specific prior written permission.
//
// THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
// AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
// IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
// ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE
// LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
// CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
// SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
// INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
// CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
// ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
// POSSIBILITY OF SUCH DAMAGE.
//
// Aegisub Project http://www.aegisub.org/


#include <algorithm>
static unsigned int clip_colorval(int val) { return std::clamp(val,0,255); }
void hsl_to_rgb(int H, int S, int L, unsigned char *R, unsigned char *G, unsigned char *B)
{
	if (S == 0) {
		*R = L;
		*G = L;
		*B = L;
		return;
	}

	if (L == 128 && S == 255) {
		switch (H) {
			case 0:
			case 255: // actually this is wrong, since this is more like 359 degrees... but it's what you'd expect (sadly :)
				*R = 255;
				*G = 0;
				*B = 0;
				return;
			case 43:
				*R = 255;
				*G = 255;
				*B = 0;
				return;
			case 85:
				*R = 0;
				*G = 255;
				*B = 0;
				return;
			case 128:
				*R = 0;
				*G = 255;
				*B = 255;
				return;
			case 171:
				*R = 0;
				*G = 0;
				*B = 255;
				return;
			case 213:
				*R = 255;
				*G = 0;
				*B = 255;
				return;
		}
	}

	float h, s, l, r, g, b;
	h = H / 255.f;
	s = S / 255.f;
	l = L / 255.f;

	float temp2;
	if (l < .5f) {
		temp2 = l * (1.f + s);
	} else {
		temp2 = l + s - l*s;
	}

	float temp1 = 2.f * l - temp2;

	// assume h is in range [0;1]
	float temp3[3];
	temp3[0] = h + 1.f/3.f;
	if (temp3[0] > 1.f) temp3[0] -= 1.f;
	temp3[1] = h;
	temp3[2] = h - 1.f/3.f;
	if (temp3[2] < 0.f) temp3[2] += 1.f;

	if (6.f * temp3[0] < 1.f)
		r = temp1 + (temp2 - temp1) * 6.f * temp3[0];
	else if (2.f * temp3[0] < 1.f)
		r = temp2;
	else if (3.f * temp3[0] < 2.f)
		r = temp1 + (temp2 - temp1) * ((2.f/3.f) - temp3[0]) * 6.f;
	else
		r = temp1;

	if (6.f * temp3[1] < 1.f)
		g = temp1 + (temp2 - temp1) * 6.f * temp3[1];
	else if (2.f * temp3[1] < 1.f)
		g = temp2;
	else if (3.f * temp3[1] < 2.f)
		g = temp1 + (temp2 - temp1) * ((2.f/3.f) - temp3[1]) * 6.f;
	else
		g = temp1;

	if (6.f * temp3[2] < 1.f)
		b = temp1 + (temp2 - temp1) * 6.f * temp3[2];
	else if (2.f * temp3[2] < 1.f)
		b = temp2;
	else if (3.f * temp3[2] < 2.f)
		b = temp1 + (temp2 - temp1) * ((2.f/3.f) - temp3[2]) * 6.f;
	else
		b = temp1;

	*R = clip_colorval((int)(r*255));
	*G = clip_colorval((int)(g*255));
	*B = clip_colorval((int)(b*255));
}
