import Foundation

/// Python's `shlex.split` (POSIX) and `shlex.join`, which `pr_loop.gates.argv` uses to pick argv or `bash -c`.
enum ShellWords {
    private static let safe = Set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_@%+=:,./-")

    /// The words of `text`, or nil where Python raises (an unclosed quote or a trailing backslash).
    static func split(_ text: String) -> [String]? {
        let chars = Array(text)
        var words = [String]()
        var word = ""
        var inWord = false
        var quote: Character?
        var i = 0
        while i < chars.count {
            let c = chars[i]
            i += 1
            if let open = quote {
                if c == open {
                    quote = nil
                } else if open == "\"", c == "\\", i < chars.count, chars[i] == "\"" || chars[i] == "\\" {
                    word.append(chars[i])
                    i += 1
                } else {
                    word.append(c)
                }
            } else if c == "\\" {
                guard i < chars.count else { return nil }
                word.append(chars[i])
                i += 1
                inWord = true
            } else if c == "'" || c == "\"" {
                quote = c
                inWord = true
            } else if c == " " || c == "\t" || c == "\n" || c == "\r" {
                if inWord { words.append(word) }
                word = ""
                inWord = false
            } else {
                word.append(c)
                inWord = true
            }
        }
        guard quote == nil else { return nil }
        return inWord ? words + [word] : words
    }

    static func quote(_ word: String) -> String {
        if word.isEmpty { return "''" }
        if word.allSatisfy(safe.contains) { return word }
        return "'" + word.replacingOccurrences(of: "'", with: "'\"'\"'") + "'"
    }

    static func isPlain(_ text: String) -> Bool {
        split(text).map { $0.map(quote).joined(separator: " ") == text } ?? false
    }
}
