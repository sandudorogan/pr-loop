import SwiftUI

/// The divider before a trailing column. Dragging it sets the column's width: a hairline that takes the pointer
/// 4 pt to each side.
struct ResizeHandle: View {
    @Binding var width: Double
    let range: ClosedRange<Double>
    @State private var start: Double?

    var body: some View {
        Divider()
            .overlay {
                Color.clear
                    .frame(width: 9)
                    .contentShape(.rect)
                    .pointerStyle(.columnResize)
                    .gesture(drag)
            }
            .zIndex(1)
    }

    private var drag: some Gesture {
        DragGesture(minimumDistance: 0, coordinateSpace: .global)
            .onChanged { drag in
                let base = start ?? width
                start = base
                width = min(max(base - drag.translation.width, range.lowerBound), range.upperBound)
            }
            .onEnded { _ in start = nil }
    }
}
