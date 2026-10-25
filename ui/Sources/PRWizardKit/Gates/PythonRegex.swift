import Foundation

/// Whether Python's `re.compile` would take `pattern`, judged by ICU's `NSRegularExpression`.
///
/// ICU spells named groups `(?<n>…)` and `(?P=n)` as `\k<n>`, so those two are translated first.
/// Remaining differences: ICU rejects a literal `{` that opens no interval (`a{x}`) and a nested `[` in a set
/// (`[[]`), which Python takes. Python rejects `\p{L}` and, before 3.11, possessive quantifiers, which ICU takes.
enum PythonRegex {
    static func compiles(_ pattern: String) -> Bool {
        let icu = pattern.replacingOccurrences(of: "(?P<", with: "(?<")
            .replacingOccurrences(of: #"\(\?P=(\w+)\)"#, with: #"\\k<$1>"#, options: .regularExpression)
        return (try? NSRegularExpression(pattern: icu)) != nil
    }
}
