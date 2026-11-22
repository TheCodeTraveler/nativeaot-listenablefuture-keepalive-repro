using Android.Util;

namespace Repro;

static class Log
{
    public const string Tag = "KeepAliveRepro";

    public static void Line(string key, params (string Name, object? Value)[] fields)
    {
        var parts = new List<string>(fields.Length + 1) { key };
        foreach (var (name, value) in fields)
        {
            var text = Convert.ToString(value, System.Globalization.CultureInfo.InvariantCulture) ?? "";
            parts.Add(text.Contains(' ') ? $"{name}=\"{text}\"" : $"{name}={text}");
        }

        Android.Util.Log.Info(Tag, string.Join(' ', parts));
    }
}
