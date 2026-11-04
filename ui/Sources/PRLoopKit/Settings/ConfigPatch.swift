/// RFC 7396 merge patch from one config tree to another, changed keys only.
public enum ConfigPatch {
    /// Objects recurse, a dropped key becomes `null`, arrays and scalars replace whole. `nil` when nothing changed.
    public static func diff(_ base: JSONValue, _ target: JSONValue) -> JSONValue? {
        guard base != target else { return nil }
        guard case .object(let base) = base, case .object(let target) = target else { return target }
        let dropped = base.keys.filter { target[$0] == nil }.map { ($0, JSONValue.null) }
        let changed = target.compactMap { key, value in
            guard let old = base[key] else { return (key, value) }
            return diff(old, value).map { (key, $0) }
        }
        return .object(JSONObject(dropped + changed))
    }
}
