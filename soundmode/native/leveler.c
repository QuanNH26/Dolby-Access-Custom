/* MemLeveler - VST2 (x64) volume leveler with a long "memory", written for soundmode to copy the measured
   behaviour of Dolby's volume leveler. No VST SDK needed: the few ABI structs are declared below.

   Algorithm = soundmode/levmodel.py (fitted to Dolby measurements), evaluated once per 20 ms frame:
     S   short-term power (one-pole over frame powers, ts)        L = 10*log10(S)
     I   long-term memory level, updated only when L >= I - gate; rises with tiu, falls with tid
     Gs  = clamp(g0 + k*(L0 - I), gmin, gmax)
     F   fast reduction toward (1-1/rf)*max(0, L - I - thr), attack tfa, release tfr
     G   = Gs - F dB, applied from the next frame on, linearly interpolated across the frame
   Settings: EAPO line  VSTPlugin: Library "...MemLeveler.dll" ChunkData "<base64 of 'k=v;k=v'>"
   keys: ts gate tiu tid g0 k L0 gmin gmax thr rf tfa tfr i0   (seconds / dB)
   Adaptive treble (ieq=1): see soundmode/ieqmodel.py; high shelf at q_fh with gain qg - q_base, applied before the leveler.
   keys: ieq q_ts q_tru q_trd q_b0 q_a q_c q_f0 q_gmin q_gmax q_tg q_base q_fh
   Adaptive bass (bass=1): same model on LP 200 Hz / BP 1 kHz, low shelf at l_fl.
   keys: bass l_ts l_tru l_trd l_b0 l_a l_c l_f0 l_gmin l_gmax l_tg l_base l_fl */
#define _USE_MATH_DEFINES
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#ifdef _WIN32
#define EXPORT __declspec(dllexport)
#else
#define EXPORT
#endif

typedef struct AEffect AEffect;
typedef intptr_t (*audioMasterCallback)(AEffect*, int32_t, int32_t, intptr_t, void*, float);
typedef intptr_t (*DispatcherProc)(AEffect*, int32_t, int32_t, intptr_t, void*, float);
typedef void (*ProcessProc)(AEffect*, float**, float**, int32_t);
typedef void (*ProcessDoubleProc)(AEffect*, double**, double**, int32_t);
typedef void (*SetParameterProc)(AEffect*, int32_t, float);
typedef float (*GetParameterProc)(AEffect*, int32_t);

struct AEffect {
    int32_t magic;
    DispatcherProc dispatcher;
    ProcessProc process;
    SetParameterProc setParameter;
    GetParameterProc getParameter;
    int32_t numPrograms, numParams, numInputs, numOutputs, flags;
    intptr_t resvd1, resvd2;
    int32_t initialDelay, realQualities, offQualities;
    float ioRatio;
    void* object;
    void* user;
    int32_t uniqueID, version;
    ProcessProc processReplacing;
    ProcessDoubleProc processDoubleReplacing;
    char future[56];
};

enum { effOpen = 0, effClose = 1, effGetParamName = 8, effSetSampleRate = 10, effSetBlockSize = 11, effMainsChanged = 12,
       effGetChunk = 23, effSetChunk = 24, effGetPlugCategory = 35, effGetEffectName = 45, effGetVendorString = 47,
       effGetProductString = 48, effGetVendorVersion = 49, effCanDo = 51, effGetVstVersion = 58 };
#define FLAG_CAN_REPLACING (1 << 4)
#define FLAG_PROGRAM_CHUNKS (1 << 5)
#define MAGIC 0x56737450 /* 'VstP' */

typedef struct { double b0, b1, b2, a1, a2, x1, x2, y1, y2; } Biquad;

static double bq_run(Biquad* q, double x) {
    double y = q->b0 * x + q->b1 * q->x1 + q->b2 * q->x2 - q->a1 * q->y1 - q->a2 * q->y2;
    q->x2 = q->x1; q->x1 = x; q->y2 = q->y1; q->y1 = y; return y;
}

/* RBJ cookbook: kind 0 = high-pass, 1 = band-pass (0 dB peak), 2 = high shelf, 3 = low shelf (S = 1), 4 = low-pass */
static void bq_set(Biquad* q, int kind, double f0, double Q, double gdb, double fs) {
    double w = 2 * M_PI * f0 / fs, cw = cos(w), sw = sin(w), b0, b1, b2, a0, a1, a2;
    if (kind == 3) {
        double A = pow(10.0, gdb / 40.0), al = sw / 2 * sqrt(2.0), s = 2 * sqrt(A) * al;
        b0 = A * ((A + 1) - (A - 1) * cw + s); b1 = 2 * A * ((A - 1) - (A + 1) * cw); b2 = A * ((A + 1) - (A - 1) * cw - s);
        a0 = (A + 1) + (A - 1) * cw + s; a1 = -2 * ((A - 1) + (A + 1) * cw); a2 = (A + 1) + (A - 1) * cw - s;
    } else if (kind == 2) {
        double A = pow(10.0, gdb / 40.0), al = sw / 2 * sqrt(2.0), s = 2 * sqrt(A) * al;
        b0 = A * ((A + 1) + (A - 1) * cw + s); b1 = -2 * A * ((A - 1) + (A + 1) * cw); b2 = A * ((A + 1) + (A - 1) * cw - s);
        a0 = (A + 1) - (A - 1) * cw + s; a1 = 2 * ((A - 1) - (A + 1) * cw); a2 = (A + 1) - (A - 1) * cw - s;
    } else {
        double al = sw / (2 * Q);
        if (kind == 0) { b0 = (1 + cw) / 2; b1 = -(1 + cw); b2 = (1 + cw) / 2; }
        else if (kind == 4) { b0 = (1 - cw) / 2; b1 = 1 - cw; b2 = (1 - cw) / 2; }
        else { b0 = al; b1 = 0; b2 = -al; }
        a0 = 1 + al; a1 = -2 * cw; a2 = 1 - al;
    }
    q->b0 = b0 / a0; q->b1 = b1 / a0; q->b2 = b2 / a0; q->a1 = a1 / a0; q->a2 = a2 / a0;
}

typedef struct {
    AEffect fx;
    double fs;
    /* leveler */
    double ts, gate, tiu, tid, g0, k, L0, gmin, gmax, thr, rf, tfa, tfr, i0;
    /* adaptive treble (Intelligent EQ), active when ieq != 0 */
    double ieq, q_ts, q_tru, q_trd, q_b0, q_a, q_c, q_f0, q_gmin, q_gmax, q_tg, q_base, q_fh;
    double bass, l_ts, l_tru, l_trd, l_b0, l_a, l_c, l_f0, l_gmin, l_gmax, l_tg, l_base, l_fl;
    double S, I, F, G, gprev, acc;          /* leveler state */
    double qS, qR, qg, ph, pm;              /* IEQ state + frame accumulators */
    double lS, lR, lg, pl;                  /* bass state */
    Biquad hp, bp, lp, shelf[2], lshelf[2];
    int frame, count;
    int primed, warm, pn; double pacc;                       /* warm start: adopt the first audio's level, then ease in */
    char chunk[2048];
} Lev;

#define NKEYS 40
static const char* KEYS[NKEYS] = {"ts", "gate", "tiu", "tid", "g0", "k", "L0", "gmin", "gmax", "thr", "rf", "tfa", "tfr", "i0",
    "ieq", "q_ts", "q_tru", "q_trd", "q_b0", "q_a", "q_c", "q_f0", "q_gmin", "q_gmax", "q_tg", "q_base", "q_fh",
    "bass", "l_ts", "l_tru", "l_trd", "l_b0", "l_a", "l_c", "l_f0", "l_gmin", "l_gmax", "l_tg", "l_base", "l_fl"};
static double* field(Lev* l, int i) {
    double* f[NKEYS] = {&l->ts, &l->gate, &l->tiu, &l->tid, &l->g0, &l->k, &l->L0, &l->gmin, &l->gmax, &l->thr, &l->rf, &l->tfa, &l->tfr, &l->i0,
        &l->ieq, &l->q_ts, &l->q_tru, &l->q_trd, &l->q_b0, &l->q_a, &l->q_c, &l->q_f0, &l->q_gmin, &l->q_gmax, &l->q_tg, &l->q_base, &l->q_fh,
        &l->bass, &l->l_ts, &l->l_tru, &l->l_trd, &l->l_b0, &l->l_a, &l->l_c, &l->l_f0, &l->l_gmin, &l->l_gmax, &l->l_tg, &l->l_base, &l->l_fl};
    return f[i];
}

static void defaults(Lev* l) {
    double d[NKEYS] = {0.4, 15, 10, 20, 6, 0.4, -30, -3, 12, 3, 2, 0.3, 0.8, -40,
                       0, 0.5, 30, 30, -1.5, 0.5, 0.5, 0, -4.7, 4.8, 0.3, -1.5, 3000,
                       0, 0.5, 30, 30, 4.0, 0.5, 0.0, 6.5, 0, 4.5, 0.3, 3.3, 200};
    for (int i = 0; i < NKEYS; i++) *field(l, i) = d[i];
}

static double gain_now(Lev* l) {
    double gs = l->g0 + l->k * (l->L0 - l->I);
    if (gs < l->gmin) gs = l->gmin; if (gs > l->gmax) gs = l->gmax;
    return gs - l->F;
}

static void set_shelf(Lev* l) {
    for (int c = 0; c < 2; c++) {
        Biquad* q = &l->shelf[c]; double x1 = q->x1, x2 = q->x2, y1 = q->y1, y2 = q->y2;
        bq_set(q, 2, l->q_fh, 0.7071, l->ieq ? l->qg - l->q_base : 0.0, l->fs);
        q->x1 = x1; q->x2 = x2; q->y1 = y1; q->y2 = y2;
        q = &l->lshelf[c]; x1 = q->x1; x2 = q->x2; y1 = q->y1; y2 = q->y2;
        bq_set(q, 3, l->l_fl, 0.7071, l->bass ? l->lg - l->l_base : 0.0, l->fs);
        q->x1 = x1; q->x2 = x2; q->y1 = y1; q->y2 = y2;
    }
}

static void reset(Lev* l) {
    l->frame = (int)(0.02 * l->fs + 0.5); if (l->frame < 1) l->frame = 1;
    l->S = pow(10.0, l->i0 / 10.0); l->I = l->i0; l->F = 0;
    l->G = 0; l->gprev = 1.0; l->acc = 0; l->count = 0;   /* unity until audio arrives (see end_of_frame) */
    l->primed = 0; l->warm = 0; l->pn = 0; l->pacc = 0;
    l->qS = l->qR = l->q_f0; l->qg = l->q_b0; l->ph = l->pm = 0;
    l->lS = l->lR = l->l_f0; l->lg = l->l_b0; l->pl = 0;
    memset(&l->hp, 0, sizeof l->hp); memset(&l->bp, 0, sizeof l->bp); memset(l->shelf, 0, sizeof l->shelf);
    memset(&l->lp, 0, sizeof l->lp); memset(l->lshelf, 0, sizeof l->lshelf); bq_set(&l->lp, 4, 200, 0.7071, 0, l->fs);
    bq_set(&l->hp, 0, 3000, 0.7071, 0, l->fs); bq_set(&l->bp, 1, 1000, 0.7071, 0, l->fs);
    set_shelf(l);
}

static void parse(Lev* l, const char* s, size_t n) {
    char buf[2048]; if (n >= sizeof buf) n = sizeof buf - 1; memcpy(buf, s, n); buf[n] = 0;
    for (char* tok = strtok(buf, "; \r\n"); tok; tok = strtok(NULL, "; \r\n")) {
        char* eq = strchr(tok, '='); if (!eq) continue; *eq = 0;
        for (int i = 0; i < NKEYS; i++) if (!strcmp(tok, KEYS[i])) *field(l, i) = atof(eq + 1);
    }
    reset(l);
}

static void serialize(Lev* l) {
    size_t o = 0; l->chunk[0] = 0;
    for (int i = 0; i < NKEYS; i++)
        o += snprintf(l->chunk + o, sizeof l->chunk - o, "%s%s=%.6g", i ? ";" : "", KEYS[i], *field(l, i));
}

static double co(double tau, double dt) { return exp(-dt / (tau > 1e-3 ? tau : 1e-3)); }

#define WARM_FRAMES 50      /* 1 s: limit gain steps to WARM_STEP dB per 20 ms frame after (re)start */
#define WARM_STEP 0.25

static void end_of_frame(Lev* l) {
    double dt = 0.02, p = l->acc / l->frame;
    if (!l->primed) {
        /* A new instance (mode switch, Off->On) has no history. Starting from the configured quiet memory (i0) makes
           the leveler boost loud music by up to +13 dB for many seconds, which the limiter then crushes. Instead adopt
           the level and spectral balance of the first real audio frame, as if it had been playing for a while. */
        if (p < 1e-7) { l->ph = l->pm = l->pl = 0; return; }              /* below -70 dBFS: wait, stay at unity */
        l->pacc += p;                                                     /* average the first 200 ms of audio */
        if (++l->pn < 10) { l->ph = l->pm = l->pl = 0; return; }
        p = l->pacc / l->pn;
        double Lp = 10.0 * log10(p) - 8.0;                                 /* memory a bit under the current level, */
        l->S = p; l->I = Lp > l->i0 ? Lp : l->i0; l->F = 0;              /* never lower than i0 (quiet starts) */
        if (l->ieq) l->qS = l->qR = 10.0 * log10((l->ph / l->frame + 1e-20) / (l->pm / l->frame + 1e-20));
        if (l->bass) l->lS = l->lR = 10.0 * log10((l->pl / l->frame + 1e-20) / (l->pm / l->frame + 1e-20));
        l->primed = 1;
    }
    double as = co(l->ts, dt);
    l->S = as * l->S + (1 - as) * p;
    double L = 10.0 * log10(l->S + 1e-20);
    if (L >= l->I - l->gate) { double a = L > l->I ? co(l->tiu, dt) : co(l->tid, dt); l->I = a * l->I + (1 - a) * L; }
    double ft = (1.0 - 1.0 / (l->rf > 1.0 ? l->rf : 1.0)) * (L - l->I - l->thr > 0 ? L - l->I - l->thr : 0);
    double a = ft > l->F ? co(l->tfa, dt) : co(l->tfr, dt);
    l->F = a * l->F + (1 - a) * ft;
    double gt = gain_now(l);
    if (l->warm < WARM_FRAMES) {      /* ease from unity into the leveler's gain */
        double d = gt - l->G; if (d > WARM_STEP) d = WARM_STEP; if (d < -WARM_STEP) d = -WARM_STEP;
        l->G += d; l->warm++;
    } else l->G = gt;
    if (l->ieq) {   /* adaptive treble */
        double f = 10.0 * log10((l->ph / l->frame + 1e-20) / (l->pm / l->frame + 1e-20));
        double aq = co(l->q_ts, dt); l->qS = aq * l->qS + (1 - aq) * f;
        double ar = l->qS > l->qR ? co(l->q_tru, dt) : co(l->q_trd, dt); l->qR = ar * l->qR + (1 - ar) * l->qS;
        double T = l->q_b0 - l->q_a * (l->qS - l->q_f0) - l->q_c * (l->qR - l->q_f0);
        if (T < l->q_gmin) T = l->q_gmin; if (T > l->q_gmax) T = l->q_gmax;
        double ag = co(l->q_tg, dt); l->qg = ag * l->qg + (1 - ag) * T;
    }
    if (l->bass) {   /* adaptive bass, same model on the low band */
        double f = 10.0 * log10((l->pl / l->frame + 1e-20) / (l->pm / l->frame + 1e-20));
        double aq = co(l->l_ts, dt); l->lS = aq * l->lS + (1 - aq) * f;
        double ar = l->lS > l->lR ? co(l->l_tru, dt) : co(l->l_trd, dt); l->lR = ar * l->lR + (1 - ar) * l->lS;
        double T = l->l_b0 - l->l_a * (l->lS - l->l_f0) - l->l_c * (l->lR - l->l_f0);
        if (T < l->l_gmin) T = l->l_gmin; if (T > l->l_gmax) T = l->l_gmax;
        double ag = co(l->l_tg, dt); l->lg = ag * l->lg + (1 - ag) * T;
    }
    if (l->ieq || l->bass) set_shelf(l);
    l->ph = l->pm = l->pl = 0;
}

static void processReplacing(AEffect* e, float** in, float** out, int32_t n) {
    Lev* l = (Lev*)e->object;
    int ch = e->numInputs;
    double gnew = pow(10.0, l->G / 20.0);
    for (int i = 0; i < n; i++) {
        double mono = 0;
        for (int c = 0; c < ch; c++) mono += in[c][i];
        mono /= ch;
        if (l->ieq || l->bass) { double m = bq_run(&l->bp, mono); l->pm += m * m; }
        if (l->ieq) { double h = bq_run(&l->hp, mono); l->ph += h * h; }
        if (l->bass) { double lo = bq_run(&l->lp, mono); l->pl += lo * lo; }
        double y[2], s = 0;
        for (int c = 0; c < ch && c < 2; c++) {
            y[c] = l->ieq ? bq_run(&l->shelf[c], in[c][i]) : in[c][i];
            if (l->bass) y[c] = bq_run(&l->lshelf[c], y[c]);
            s += y[c] * y[c];
        }
        l->acc += s / ch;
        double g = l->gprev + (gnew - l->gprev) * (double)(l->count + 1) / l->frame;
        for (int c = 0; c < ch && c < 2; c++) out[c][i] = (float)(y[c] * g);
        if (++l->count >= l->frame) {
            end_of_frame(l); l->count = 0; l->acc = 0; l->gprev = gnew; gnew = pow(10.0, l->G / 20.0);
        }
    }
}

static void process(AEffect* e, float** in, float** out, int32_t n) { processReplacing(e, in, out, n); }
static void setParameter(AEffect* e, int32_t i, float v) { (void)e; (void)i; (void)v; }
static float getParameter(AEffect* e, int32_t i) { (void)e; (void)i; return 0; }

static intptr_t dispatcher(AEffect* e, int32_t op, int32_t idx, intptr_t val, void* ptr, float opt) {
    Lev* l = (Lev*)e->object; (void)idx;
    switch (op) {
    case effClose: free(l); return 1;
    case effSetSampleRate: l->fs = opt > 0 ? opt : 44100; reset(l); return 1;
    case effMainsChanged: if (val) reset(l); return 1;
    case effGetChunk: serialize(l); *(void**)ptr = l->chunk; return (intptr_t)strlen(l->chunk);
    case effSetChunk: parse(l, (const char*)ptr, (size_t)val); return 1;
    case effGetPlugCategory: return 1; /* kPlugCategEffect */
    case effGetEffectName: case effGetProductString: strcpy((char*)ptr, "MemLeveler"); return 1;
    case effGetVendorString: strcpy((char*)ptr, "soundmode"); return 1;
    case effGetVendorVersion: return 100;
    case effGetVstVersion: return 2400;
    case effCanDo: return 0;
    default: return 0;
    }
}

EXPORT AEffect* VSTPluginMain(audioMasterCallback host) {
    (void)host;
    Lev* l = (Lev*)calloc(1, sizeof(Lev));
    if (!l) return NULL;
    l->fs = 44100; defaults(l); reset(l);
    AEffect* e = &l->fx;
    e->magic = MAGIC; e->dispatcher = dispatcher; e->process = process; e->processReplacing = processReplacing;
    e->setParameter = setParameter; e->getParameter = getParameter;
    e->numPrograms = 1; e->numParams = 0; e->numInputs = 2; e->numOutputs = 2;
    e->flags = FLAG_CAN_REPLACING | FLAG_PROGRAM_CHUNKS;
    e->object = l; e->uniqueID = 0x4D4C6576; /* 'MLev' */ e->version = 100; e->ioRatio = 1.0f;
    return e;
}
EXPORT AEffect* main_plugin(audioMasterCallback host) { return VSTPluginMain(host); }
