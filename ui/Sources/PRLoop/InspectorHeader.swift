import PRLoopKit
import SwiftUI

struct InspectorHeader: View {
    let model: InspectorModel

    var body: some View {
        let item = model.item
        let status = StatusStyle(item.status)
        let author = item.isMine ? "you" : item.author
        VStack(alignment: .leading, spacing: 6) {
            Text(model.title).font(.caption.weight(.semibold)).foregroundStyle(.tint)
            Text(item.title).font(.title3.weight(.semibold)).fixedSize(horizontal: false, vertical: true)
            Text("by \(author) · pushed \(item.pushedAt, format: .relative(presentation: .named))")
                .font(.callout).foregroundStyle(.secondary)
            Flow {
                Chip(tint: status.tone.color) { Label(status.label, systemImage: status.symbol) }
                if item.isDraft { Chip(tint: .secondary) { Label("Draft", systemImage: "pencil") } }
                Chip(tint: .secondary) {
                    HStack(spacing: 4) {
                        Text(verbatim: "+\(item.additions)").foregroundStyle(.green)
                        Text(verbatim: "−\(item.deletions)").foregroundStyle(.red)
                    }
                    .monospacedDigit()
                }
                Chip(tint: .purple) { Label(item.base, systemImage: "arrow.triangle.merge") }
                Chip(tint: .secondary) { Text(model.head).monospaced() }
                ForEach(item.labels, id: \.self) { label in
                    Chip(tint: .teal) { Label(label, systemImage: "tag") }
                }
            }
            .padding(.top, 4)
        }
        .padding(.vertical, 4)
    }
}

struct SectionTitle: View {
    let title: LocalizedStringKey
    let symbol: String
    let tint: Color

    var body: some View {
        Label {
            Text(title)
        } icon: {
            Image(systemName: symbol).foregroundStyle(tint)
        }
    }
}

struct InspectorRowStyle: LabeledContentStyle {
    func makeBody(configuration: Configuration) -> some View {
        HStack(alignment: .firstTextBaseline) {
            configuration.label.foregroundStyle(.secondary)
            Spacer()
            configuration.content.multilineTextAlignment(.trailing)
        }
    }
}

private struct Chip<Content: View>: View {
    let tint: Color
    @ViewBuilder let content: Content

    var body: some View {
        content
            .font(.caption.weight(.medium))
            .lineLimit(1)
            .foregroundStyle(tint)
            .padding(.horizontal, 8)
            .padding(.vertical, 3)
            .background(tint.opacity(0.15), in: .capsule)
    }
}

private struct Flow: Layout {
    var spacing: CGFloat = 6

    /// An unknown width stacks one chip per row, so the ideal width is the widest chip, never the sum.
    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        rows(proposal.width, subviews).size
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        let width = ProposedViewSize(width: bounds.width, height: nil)
        for (subview, point) in zip(subviews, rows(bounds.width, subviews).points) {
            subview.place(at: CGPoint(x: bounds.minX + point.x, y: bounds.minY + point.y), proposal: width)
        }
    }

    private func rows(_ proposed: CGFloat?, _ subviews: Subviews) -> (points: [CGPoint], size: CGSize) {
        let width = proposed ?? 0
        var points: [CGPoint] = []
        var x: CGFloat = 0
        var y: CGFloat = 0
        var line: CGFloat = 0
        var widest: CGFloat = 0
        for size in subviews.map({ $0.sizeThatFits(ProposedViewSize(width: proposed, height: nil)) }) {
            if x > 0, x + size.width > width {
                x = 0
                y += line + spacing
                line = 0
            }
            points.append(CGPoint(x: x, y: y))
            widest = max(widest, x + size.width)
            x += size.width + spacing
            line = max(line, size.height)
        }
        return (points, CGSize(width: widest, height: y + line))
    }
}
