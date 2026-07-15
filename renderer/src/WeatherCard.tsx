import React from "react";
import {
  Cloud,
  CloudDrizzle,
  CloudFog,
  CloudLightning,
  CloudMoon,
  CloudMoonRain,
  CloudRain,
  CloudSnow,
  CloudSun,
  Droplets,
  Eye,
  Gauge,
  MapPin,
  MoonStar,
  Sparkles,
  Sun,
  Sunrise,
  Sunset,
  Thermometer,
  Wind,
} from "lucide-react";

export type WeatherPayload = {
  locationDisplay: string;
  condition: string;
  conditionIcon: string;
  isDay: boolean;
  accentRgb: [number, number, number];
  temperatureC: number;
  temperatureF: number;
  temperaturePrimaryText?: string;
  temperatureSecondaryText?: string;
  feelsC: number | null;
  feelsF: number | null;
  feelsText?: string | null;
  humidity: number | null;
  dewPointText: string | null;
  windText: string | null;
  gustText: string | null;
  pressureText: string | null;
  precipText: string | null;
  cloudCoverText: string | null;
  visibilityText: string | null;
  sunrise: string | null;
  sunset: string | null;
  uvText: string | null;
  aqiText: string | null;
  observedText: string | null;
  heroIconDataUri: string | null;
  hourlyCards: Array<{
    label: string;
    temp: string;
    iconName?: string | null;
    precip?: string;
    wind?: string;
    iconDataUri?: string | null;
  }>;
  dailyCards: Array<{
    label: string;
    summary: string;
    temps: string;
    iconName?: string | null;
    detail?: string;
    iconDataUri?: string | null;
  }>;
};

type Theme = {
  skyTop: string;
  skyBottom: string;
  auraA: string;
  auraB: string;
  mist: string;
  panel: string;
  panelStrong: string;
  panelSoft: string;
  rail: string;
  line: string;
  lineSoft: string;
  text: string;
  textSoft: string;
  textDim: string;
  warm: string;
  cool: string;
  accent: string;
  accentSoft: string;
  iconHalo: string;
  heroDisc: string;
  shadow: string;
};

export function WeatherCard({ payload }: { payload: WeatherPayload }) {
  const rtl = containsRtl(payload.locationDisplay);
  const theme = buildTheme(payload.conditionIcon, payload.isDay, payload.accentRgb);
  const WeatherGlyph = pickWeatherGlyph(payload.conditionIcon, payload.isDay);

  const metrics = [
    { label: "Humidity", value: valueOrDash(payload.humidity !== null ? `${payload.humidity}%` : null), icon: Droplets },
    { label: "Wind", value: valueOrDash(payload.windText), icon: Wind },
    { label: "UV", value: valueOrDash(payload.uvText), icon: Sparkles },
    { label: "AQI", value: valueOrDash(payload.aqiText), icon: Gauge },
  ];

  const detailCards = [
    {
      title: "Air",
      icon: Thermometer,
      lines: [
        pair("Humidity", payload.humidity !== null ? `${payload.humidity}%` : null),
        pair("Dew point", payload.dewPointText),
        pair("Pressure", payload.pressureText),
      ],
    },
    {
      title: "Sky",
      icon: Cloud,
      lines: [
        pair("Cloud cover", payload.cloudCoverText),
        pair("Visibility", payload.visibilityText),
        pair("Precip", payload.precipText),
      ],
    },
    {
      title: payload.isDay ? "Sun + Wind" : "Moon + Wind",
      icon: payload.isDay ? Sun : MoonStar,
      lines: [
        pair("Flow", payload.windText),
        pair("Gusts", payload.gustText),
        pair("Cycle", joinPair(payload.sunrise, payload.sunset)),
      ],
    },
  ];

  return (
    <div
      id="weather-card-root"
      dir={rtl ? "rtl" : "ltr"}
      className="relative h-[1060px] w-[1500px] overflow-hidden rounded-[44px] p-[24px]"
      style={{
        color: theme.text,
        background: `linear-gradient(180deg, ${theme.skyTop} 0%, ${theme.skyBottom} 100%)`,
        boxShadow: `0 42px 120px ${theme.shadow}`,
      }}
    >
      <Atmosphere theme={theme} iconName={payload.conditionIcon} />

      <div
        className="relative h-full w-full rounded-[38px] border p-4"
        style={{
          borderColor: theme.line,
          background: "linear-gradient(180deg, rgba(5,12,22,0.20), rgba(7,12,22,0.34))",
          boxShadow: "inset 0 1px 0 rgba(255,255,255,0.18)",
        }}
      >
        <div className="grid h-full grid-cols-[1fr_344px] gap-4">
          <div className="flex h-full flex-col gap-3">
            <Panel className="relative h-[332px] overflow-hidden rounded-[36px] p-5" theme={theme} strong>
              <div
                className="absolute inset-x-5 top-4 h-7 rounded-full"
                style={{ background: `linear-gradient(90deg, ${theme.accentSoft}, rgba(255,255,255,0.05))` }}
              />
              <div className="absolute inset-y-0 right-0 w-[42%]" style={{ background: "linear-gradient(270deg, rgba(255,255,255,0.06), transparent 70%)" }} />

              <div className={`relative z-10 flex h-full ${rtl ? "flex-row-reverse" : ""}`}>
                <div className={`flex min-w-0 flex-1 flex-col justify-between ${rtl ? "pl-3 text-right" : "pr-3 text-left"}`}>
                  <div>
                    <div
                      className={`flex items-center gap-2.5 text-[18px] font-semibold tracking-[0.02em] ${rtl ? "flex-row-reverse" : ""}`}
                      style={{ color: theme.textSoft }}
                    >
                      <MapPin className="h-4.5 w-4.5 shrink-0" strokeWidth={2.3} />
                      <span className="truncate text-[21px] font-bold" style={{ color: theme.text }}>
                        {payload.locationDisplay}
                      </span>
                    </div>
                    <div className="mt-2.5 text-[24px] font-medium" style={{ color: theme.textSoft }}>
                      {payload.condition}
                    </div>
                  </div>

                  <div>
                    <div className={`flex items-end gap-4 ${rtl ? "flex-row-reverse" : ""}`}>
                      <div className="text-[92px] font-black leading-none tracking-[-0.07em]">
                        {payload.temperaturePrimaryText ?? `${Math.round(payload.temperatureC)}°C`}
                      </div>
                      <div className="pb-3 text-[46px] font-bold tracking-[-0.05em]" style={{ color: theme.cool }}>
                        / {payload.temperatureSecondaryText ?? `${Math.round(payload.temperatureF)}°F`}
                      </div>
                    </div>
                    {payload.feelsC !== null && payload.feelsF !== null ? (
                      <div className="mt-1.5 text-[20px] font-medium" style={{ color: theme.warm }}>
                        Feels like {payload.feelsText ?? `${Math.round(payload.feelsC)}°C / ${Math.round(payload.feelsF)}°F`}
                      </div>
                    ) : null}
                    {payload.observedText ? (
                      <div className="mt-1.5 text-[16px]" style={{ color: theme.textDim }}>
                        {payload.observedText}
                      </div>
                    ) : null}
                  </div>
                </div>

                <div className="relative flex w-[320px] shrink-0 items-center justify-center">
                  <div
                    className="absolute h-[216px] w-[216px] rounded-full blur-3xl"
                    style={{ background: `radial-gradient(circle, ${theme.iconHalo} 0%, transparent 72%)` }}
                  />
                  <div
                    className="absolute h-[198px] w-[198px] rounded-full border"
                    style={{
                      borderColor: theme.lineSoft,
                      background: `radial-gradient(circle at 32% 28%, rgba(255,255,255,0.18), ${theme.heroDisc})`,
                      boxShadow: "inset 0 1px 0 rgba(255,255,255,0.22)",
                    }}
                  />
                  {payload.heroIconDataUri ? (
                    <img
                      src={payload.heroIconDataUri}
                      alt=""
                      className="relative z-10 h-[172px] w-[172px] object-contain drop-shadow-[0_20px_28px_rgba(0,0,0,0.30)]"
                    />
                  ) : (
                    <WeatherGlyph className="relative z-10 h-[146px] w-[146px]" strokeWidth={1.8} />
                  )}
                </div>
              </div>
            </Panel>

            <div className="grid grid-cols-4 gap-3">
              {metrics.map((metric) => (
                <Panel key={metric.label} className="rounded-[24px] px-4 py-3.5" theme={theme}>
                  <div className={`flex items-center gap-2.5 text-[17px] ${rtl ? "flex-row-reverse justify-end text-right" : ""}`} style={{ color: theme.textDim }}>
                    <metric.icon className="h-4 w-4 shrink-0" strokeWidth={2.2} />
                    {metric.label}
                  </div>
                  <div className={`mt-1 text-[20px] font-bold leading-tight ${rtl ? "text-right" : ""}`}>{metric.value}</div>
                </Panel>
              ))}
            </div>

            <Panel className="flex-1 rounded-[34px] p-4.5" theme={theme} soft>
              <div className={`flex items-end justify-between ${rtl ? "flex-row-reverse" : ""}`}>
                <div className="text-[22px] font-bold tracking-[0.01em]">Right now</div>
                <div className="text-[14px] uppercase tracking-[0.22em]" style={{ color: theme.textDim }}>Live view</div>
              </div>

              <div className="mt-3 grid grid-cols-[1.1fr_1.9fr] gap-3">
                <Panel className="rounded-[26px] px-4 py-3.5" theme={theme} strong>
                  <div className={`flex items-center justify-between gap-3 ${rtl ? "flex-row-reverse" : ""}`}>
                    <div className="text-[31px] font-black tracking-[-0.05em]">
                      {payload.temperaturePrimaryText ?? `${Math.round(payload.temperatureC)}°C`}
                    </div>
                    <div className="text-[17px] font-bold" style={{ color: theme.cool }}>
                      {payload.temperatureSecondaryText ?? `${Math.round(payload.temperatureF)}°F`}
                    </div>
                  </div>
                  <div className="mt-2.5 text-[13px] leading-tight" style={{ color: theme.textDim }}>
                    {payload.observedText || payload.condition}
                  </div>
                </Panel>

                <Panel className="rounded-[26px] px-4 py-3.5" theme={theme}>
                  <div className={`flex items-center gap-3 ${rtl ? "flex-row-reverse text-right" : ""}`}>
                    <div
                      className="h-3 w-3 rounded-full"
                      style={{ background: theme.accent, boxShadow: `0 0 14px ${theme.accentSoft}` }}
                    />
                    <div className="min-w-0 truncate text-[18px] font-medium" style={{ color: theme.textSoft }}>
                      {payload.condition}
                      {payload.observedText ? ` • ${payload.observedText}` : ""}
                    </div>
                  </div>
                  <div className="mt-3 grid grid-cols-3 gap-2 text-[12px]" style={{ color: theme.textDim }}>
                    <MiniStat label="Humidity" value={payload.humidity !== null ? `${payload.humidity}%` : null} rtl={rtl} />
                    <MiniStat label="Precip" value={payload.precipText} rtl={rtl} />
                    <MiniStat label="Visibility" value={payload.visibilityText} rtl={rtl} />
                  </div>
                </Panel>
              </div>

              <div className="mt-3 grid grid-cols-3 gap-3">
                {detailCards.map((card) => (
                  <Panel key={card.title} className="rounded-[26px] p-3.5" theme={theme}>
                    <div className={`flex items-center gap-2.5 text-[17px] font-semibold ${rtl ? "flex-row-reverse text-right" : ""}`} style={{ color: theme.textSoft }}>
                      <card.icon className="h-4.5 w-4.5 shrink-0" strokeWidth={2.2} />
                      {card.title}
                    </div>
                    <div className={`mt-2.5 space-y-1 text-[14px] leading-[1.24] ${rtl ? "text-right" : ""}`} style={{ color: theme.textSoft }}>
                      {card.lines.filter(Boolean).map((line) => (
                        <div key={line}>{line}</div>
                      ))}
                    </div>
                  </Panel>
                ))}
              </div>

              <div className={`mt-4 flex items-end justify-between ${rtl ? "flex-row-reverse" : ""}`}>
                <div className="text-[22px] font-bold tracking-[0.01em]">Hourly outlook</div>
                <div className="text-[14px]" style={{ color: theme.textDim }}>Next 5 hours</div>
              </div>

              <div className="mt-2.5 grid grid-cols-5 gap-2.5">
                {payload.hourlyCards.slice(0, 5).map((hour, index) => (
                  <Panel key={hour.label + index} className="relative overflow-hidden rounded-[24px] p-3" theme={theme} strong={index === 0}>
                    <div className="absolute inset-x-0 top-0 h-[3px]" style={{ background: index === 0 ? theme.accent : "rgba(255,255,255,0.08)" }} />
                    <div className={`text-[15px] font-medium ${rtl ? "text-right" : ""}`} style={{ color: theme.textDim }}>
                      {hour.label}
                    </div>
                    <div className={`mt-2 flex items-center justify-between gap-2 ${rtl ? "flex-row-reverse" : ""}`}>
                      {hour.iconDataUri ? (
                        <img src={hour.iconDataUri} alt="" className="h-10 w-10 object-contain" />
                      ) : (
                        <WeatherGlyph className="h-9 w-9 shrink-0" strokeWidth={1.8} />
                      )}
                      <div className="text-[25px] font-black tracking-[-0.05em]">{hour.temp}</div>
                    </div>
                    <div className={`mt-3 space-y-0.5 text-[12px] leading-tight ${rtl ? "text-right" : ""}`} style={{ color: theme.textDim }}>
                      {hour.precip ? <div>{hour.precip}</div> : null}
                      {hour.wind ? <div>{hour.wind}</div> : null}
                    </div>
                  </Panel>
                ))}
              </div>
            </Panel>
          </div>

          <Panel className="flex h-full flex-col rounded-[36px] p-4.5" theme={theme} strong>
            <div className="text-[26px] font-bold">Forecast</div>
            <div className="mt-1 text-[16px]" style={{ color: theme.textDim }}>Next few days</div>

            <div className="mt-4 flex flex-1 flex-col gap-3">
              {payload.dailyCards.slice(0, 5).map((day, index) => (
                <Panel
                  key={day.label + index}
                  className="relative overflow-hidden rounded-[26px] p-3.5"
                  theme={theme}
                  strong={index === 0}
                >
                  <div className="absolute inset-y-0 left-0 w-[5px]" style={{ background: index === 0 ? theme.accent : "rgba(255,255,255,0.08)" }} />
                  <div className={`flex items-start justify-between gap-3 ${rtl ? "flex-row-reverse text-right" : ""}`}>
                    <div className="min-w-0 flex-1">
                      <div className="text-[17px] font-bold">{day.label}</div>
                      <div className="mt-1 text-[14px] leading-tight" style={{ color: theme.textSoft }}>
                        {day.summary}
                      </div>
                      <div className="mt-3 text-[24px] font-black tracking-[-0.05em]" style={{ color: theme.warm }}>
                        {day.temps}
                      </div>
                      {day.detail ? (
                        <div className="mt-1 text-[13px]" style={{ color: theme.textDim }}>
                          {day.detail}
                        </div>
                      ) : null}
                    </div>
                    {day.iconDataUri ? (
                      <img src={day.iconDataUri} alt="" className="mt-1 h-12 w-12 shrink-0 object-contain drop-shadow-[0_8px_14px_rgba(0,0,0,0.18)]" />
                    ) : (
                      <CloudSun className="mt-1 h-10 w-10 shrink-0" strokeWidth={1.8} />
                    )}
                  </div>
                </Panel>
              ))}
            </div>

            <Panel className="mt-3 rounded-[24px] px-4 py-3" theme={theme}>
              <div className="grid grid-cols-2 gap-2 text-[12px]" style={{ color: theme.textSoft }}>
                <FooterStat icon={Sunrise} value={valueOrDash(payload.sunrise)} />
                <FooterStat icon={Sunset} value={valueOrDash(payload.sunset)} />
                <FooterStat icon={Cloud} value={valueOrDash(payload.cloudCoverText)} />
                <FooterStat icon={Eye} value={valueOrDash(payload.visibilityText)} />
              </div>
            </Panel>
          </Panel>
        </div>
      </div>
    </div>
  );
}

function Panel({
  children,
  className,
  strong = false,
  soft = false,
  theme,
}: {
  children: React.ReactNode;
  className?: string;
  strong?: boolean;
  soft?: boolean;
  theme: Theme;
}) {
  return (
    <div
      className={className}
      style={{
        border: `1px solid ${strong ? theme.line : theme.lineSoft}`,
        background: strong ? theme.panelStrong : soft ? theme.panelSoft : theme.panel,
        boxShadow: "inset 0 1px 0 rgba(255,255,255,0.12)",
        backdropFilter: "blur(20px)",
      }}
    >
      {children}
    </div>
  );
}

function Atmosphere({ theme, iconName }: { theme: Theme; iconName: string }) {
  const stormy = iconName.includes("thunder");
  const rainy = iconName.includes("rain") || iconName.includes("drizzle") || iconName.includes("showers");
  const snowy = iconName.includes("snow") || iconName.includes("flurr");
  const night = iconName.includes("night");

  return (
    <>
      <div
        className="absolute inset-0"
        style={{
          background: `radial-gradient(circle at 18% 12%, ${theme.auraA} 0%, transparent 28%),
            radial-gradient(circle at 84% 10%, ${theme.auraB} 0%, transparent 24%),
            radial-gradient(circle at 12% 88%, rgba(255,255,255,0.08) 0%, transparent 22%),
            radial-gradient(circle at 88% 86%, rgba(255,255,255,0.07) 0%, transparent 24%)`,
        }}
      />
      <div className="absolute left-[6%] top-[14%] h-[190px] w-[540px] rounded-full blur-[44px]" style={{ background: theme.mist }} />
      <div className="absolute left-[18%] top-[20%] h-[140px] w-[420px] rounded-full blur-[34px]" style={{ background: "rgba(255,255,255,0.06)" }} />
      <div className="absolute right-[-6%] top-[64%] h-[380px] w-[540px] rounded-full blur-3xl" style={{ background: "rgba(255,255,255,0.06)" }} />
      <div className="absolute left-[-8%] top-[74%] h-[420px] w-[420px] rounded-full blur-3xl" style={{ background: "rgba(255,255,255,0.05)" }} />
      {night
        ? [[120, 86], [188, 62], [316, 118], [452, 74], [1032, 82], [1188, 116], [1350, 72]].map(([left, top]) => (
            <div
              key={`${left}-${top}`}
              className="absolute h-[3px] w-[3px] rounded-full bg-white shadow-[0_0_12px_rgba(255,255,255,0.7)]"
              style={{ left, top, opacity: 0.72 }}
            />
          ))
        : null}
      {stormy ? (
        <div
          className="absolute right-[24%] top-[2%] h-[340px] w-[220px] rotate-[12deg] blur-[1px]"
          style={{ background: "linear-gradient(180deg, rgba(255,255,255,0.00), rgba(255,255,255,0.9) 38%, rgba(130,190,255,0.0) 90%)", clipPath: "polygon(56% 0, 70% 36%, 58% 36%, 76% 100%, 36% 52%, 50% 52%, 30% 0)" }}
        />
      ) : null}
      {rainy ? (
        <div
          className="absolute inset-0 opacity-20"
          style={{
            backgroundImage:
              "repeating-linear-gradient(112deg, transparent 0 18px, rgba(255,255,255,0.22) 18px 20px, transparent 20px 38px)",
          }}
        />
      ) : null}
      {snowy ? (
        <>
          {[80, 210, 340, 520, 690, 860, 1020, 1180, 1340].map((left, idx) => (
            <div
              key={left}
              className="absolute h-[6px] w-[6px] rounded-full bg-white/80"
              style={{ left, top: 90 + (idx % 4) * 56, boxShadow: "0 0 14px rgba(255,255,255,0.6)" }}
            />
          ))}
        </>
      ) : null}
    </>
  );
}

function MiniStat({ label, value, rtl }: { label: string; value: string | null; rtl: boolean }) {
  return (
    <div className={rtl ? "text-right" : ""}>
      <div style={{ color: "rgba(255,255,255,0.58)" }}>{label}</div>
      <div className="mt-1 font-semibold text-white/90">{valueOrDash(value)}</div>
    </div>
  );
}

function FooterStat({
  icon: Icon,
  value,
}: {
  icon: typeof Sunrise;
  value: string;
}) {
  return (
    <div className="flex items-center gap-2">
      <Icon className="h-4 w-4 shrink-0" strokeWidth={2.1} />
      <span>{value}</span>
    </div>
  );
}

function buildTheme(iconName: string, isDay: boolean, [r, g, b]: [number, number, number]): Theme {
  const accent = `rgb(${r}, ${g}, ${b})`;
  const clear = iconName.includes("clear") || iconName.includes("mostly_clear");
  const cloudy = iconName.includes("cloudy") || iconName.includes("partly");
  const rainy = iconName.includes("rain") || iconName.includes("showers") || iconName.includes("drizzle");
  const stormy = iconName.includes("thunder");
  const snowy = iconName.includes("snow") || iconName.includes("flurr");

  if (stormy) {
    return {
      skyTop: "rgb(18, 32, 76)",
      skyBottom: "rgb(7, 13, 28)",
      auraA: "rgba(83,130,255,0.34)",
      auraB: "rgba(255,208,91,0.20)",
      mist: "rgba(190,216,255,0.10)",
      panel: "linear-gradient(180deg, rgba(22,34,70,0.72), rgba(12,20,44,0.72))",
      panelStrong: "linear-gradient(180deg, rgba(30,48,96,0.74), rgba(14,24,50,0.78))",
      panelSoft: "linear-gradient(180deg, rgba(18,28,56,0.60), rgba(11,18,38,0.62))",
      rail: "rgba(255,199,84,0.9)",
      line: "rgba(214,231,255,0.24)",
      lineSoft: "rgba(214,231,255,0.14)",
      text: "rgba(247,251,255,0.98)",
      textSoft: "rgba(219,232,255,0.94)",
      textDim: "rgba(169,196,236,0.9)",
      warm: "rgba(255,220,142,0.98)",
      cool: "rgba(168,205,255,0.94)",
      accent,
      accentSoft: "rgba(255,199,84,0.22)",
      iconHalo: "rgba(105,145,255,0.44)",
      heroDisc: "rgba(41,58,98,0.54)",
      shadow: "rgba(2,8,18,0.58)",
    };
  }

  if (rainy) {
    return {
      skyTop: isDay ? "rgb(56, 101, 156)" : "rgb(18, 42, 84)",
      skyBottom: isDay ? "rgb(18, 52, 92)" : "rgb(8, 18, 40)",
      auraA: "rgba(139,205,255,0.26)",
      auraB: "rgba(104,152,232,0.18)",
      mist: "rgba(226,240,255,0.09)",
      panel: "linear-gradient(180deg, rgba(18,49,96,0.66), rgba(12,33,68,0.7))",
      panelStrong: "linear-gradient(180deg, rgba(34,79,145,0.70), rgba(15,42,86,0.74))",
      panelSoft: "linear-gradient(180deg, rgba(14,40,78,0.58), rgba(10,28,56,0.60))",
      rail: "rgba(119,192,255,0.92)",
      line: "rgba(224,240,255,0.22)",
      lineSoft: "rgba(224,240,255,0.12)",
      text: "rgba(247,251,255,0.98)",
      textSoft: "rgba(223,237,255,0.94)",
      textDim: "rgba(180,207,240,0.88)",
      warm: "rgba(255,227,160,0.94)",
      cool: "rgba(186,220,255,0.94)",
      accent,
      accentSoft: "rgba(119,192,255,0.22)",
      iconHalo: "rgba(129,190,248,0.34)",
      heroDisc: "rgba(32,72,126,0.40)",
      shadow: "rgba(4,15,30,0.52)",
    };
  }

  if (snowy) {
    return {
      skyTop: isDay ? "rgb(108, 148, 182)" : "rgb(44, 72, 112)",
      skyBottom: isDay ? "rgb(42, 82, 112)" : "rgb(12, 25, 52)",
      auraA: "rgba(237,247,255,0.24)",
      auraB: "rgba(182,212,255,0.18)",
      mist: "rgba(255,255,255,0.12)",
      panel: "linear-gradient(180deg, rgba(34,70,108,0.62), rgba(20,44,72,0.68))",
      panelStrong: "linear-gradient(180deg, rgba(60,105,154,0.65), rgba(23,52,86,0.72))",
      panelSoft: "linear-gradient(180deg, rgba(28,58,90,0.56), rgba(16,34,58,0.60))",
      rail: "rgba(238,248,255,0.92)",
      line: "rgba(233,244,255,0.26)",
      lineSoft: "rgba(233,244,255,0.16)",
      text: "rgba(249,252,255,0.98)",
      textSoft: "rgba(232,241,255,0.95)",
      textDim: "rgba(193,214,236,0.9)",
      warm: "rgba(255,232,182,0.95)",
      cool: "rgba(210,229,255,0.94)",
      accent,
      accentSoft: "rgba(219,240,255,0.18)",
      iconHalo: "rgba(236,246,255,0.30)",
      heroDisc: "rgba(84,110,144,0.28)",
      shadow: "rgba(5,14,30,0.48)",
    };
  }

  if (clear && isDay) {
    return {
      skyTop: "rgb(123, 181, 246)",
      skyBottom: "rgb(38, 104, 205)",
      auraA: "rgba(255,231,160,0.32)",
      auraB: "rgba(129,198,255,0.22)",
      mist: "rgba(255,255,255,0.10)",
      panel: "linear-gradient(180deg, rgba(28,89,172,0.56), rgba(18,65,136,0.58))",
      panelStrong: "linear-gradient(180deg, rgba(52,116,214,0.62), rgba(24,79,167,0.64))",
      panelSoft: "linear-gradient(180deg, rgba(25,76,148,0.52), rgba(15,54,111,0.56))",
      rail: "rgba(255,204,81,0.94)",
      line: "rgba(235,245,255,0.24)",
      lineSoft: "rgba(235,245,255,0.15)",
      text: "rgba(248,252,255,0.99)",
      textSoft: "rgba(234,244,255,0.94)",
      textDim: "rgba(188,214,255,0.90)",
      warm: "rgba(255,227,149,0.98)",
      cool: "rgba(206,227,255,0.94)",
      accent,
      accentSoft: "rgba(255,204,81,0.20)",
      iconHalo: "rgba(255,208,110,0.34)",
      heroDisc: "rgba(149,188,244,0.26)",
      shadow: "rgba(7,22,48,0.44)",
    };
  }

  if (cloudy && isDay) {
    return {
      skyTop: "rgb(116, 152, 183)",
      skyBottom: "rgb(56, 97, 143)",
      auraA: "rgba(245,249,255,0.18)",
      auraB: "rgba(171,206,244,0.16)",
      mist: "rgba(255,255,255,0.09)",
      panel: "linear-gradient(180deg, rgba(42,85,139,0.56), rgba(28,61,104,0.58))",
      panelStrong: "linear-gradient(180deg, rgba(66,112,171,0.62), rgba(33,70,120,0.64))",
      panelSoft: "linear-gradient(180deg, rgba(30,63,106,0.52), rgba(20,43,76,0.56))",
      rail: "rgba(220,234,255,0.88)",
      line: "rgba(233,244,255,0.22)",
      lineSoft: "rgba(233,244,255,0.13)",
      text: "rgba(248,252,255,0.98)",
      textSoft: "rgba(227,239,255,0.94)",
      textDim: "rgba(182,205,232,0.9)",
      warm: "rgba(255,227,164,0.96)",
      cool: "rgba(207,223,246,0.94)",
      accent,
      accentSoft: "rgba(220,234,255,0.16)",
      iconHalo: "rgba(213,228,245,0.24)",
      heroDisc: "rgba(104,133,168,0.24)",
      shadow: "rgba(7,17,32,0.42)",
    };
  }

  return {
    skyTop: "rgb(20, 38, 82)",
    skyBottom: "rgb(7, 14, 30)",
    auraA: "rgba(126,168,255,0.24)",
    auraB: "rgba(216,233,255,0.10)",
    mist: "rgba(255,255,255,0.08)",
    panel: "linear-gradient(180deg, rgba(18,31,66,0.62), rgba(12,24,50,0.62))",
    panelStrong: "linear-gradient(180deg, rgba(28,46,88,0.66), rgba(15,28,58,0.68))",
    panelSoft: "linear-gradient(180deg, rgba(15,28,56,0.58), rgba(10,20,40,0.60))",
    rail: "rgba(196,220,255,0.92)",
    line: "rgba(226,239,255,0.22)",
    lineSoft: "rgba(226,239,255,0.12)",
    text: "rgba(247,251,255,0.98)",
    textSoft: "rgba(231,239,255,0.95)",
    textDim: "rgba(166,194,245,0.9)",
    warm: "rgba(255,228,164,0.96)",
    cool: "rgba(185,214,255,0.92)",
    accent,
    accentSoft: "rgba(166,194,245,0.12)",
    iconHalo: "rgba(144,176,255,0.24)",
    heroDisc: "rgba(36,54,96,0.42)",
    shadow: "rgba(2,8,18,0.60)",
  };
}

function containsRtl(value: string) {
  return /[\u0590-\u08FF]/.test(value);
}

function valueOrDash(value: string | null) {
  return value || "N/A";
}

function pair(label: string, value: string | null) {
  return value ? `${label}: ${value}` : null;
}

function joinPair(a: string | null, b: string | null) {
  if (a && b) return `${a} / ${b}`;
  return a || b;
}

function pickWeatherGlyph(iconName: string, isDay: boolean) {
  if (iconName.includes("thunder")) return CloudLightning;
  if (iconName.includes("snow") || iconName.includes("flurr")) return CloudSnow;
  if (iconName.includes("rain") || iconName.includes("showers")) return isDay ? CloudRain : CloudMoonRain;
  if (iconName.includes("drizzle")) return CloudDrizzle;
  if (iconName.includes("fog") || iconName.includes("haze")) return CloudFog;
  if (iconName.includes("partly")) return isDay ? CloudSun : CloudMoon;
  if (iconName.includes("clear")) return isDay ? Sun : MoonStar;
  return Cloud;
}
