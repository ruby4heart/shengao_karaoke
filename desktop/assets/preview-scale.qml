import QtQuick
import QtMultimedia

Rectangle {
    color: "#0c1423"
    VideoOutput {
        objectName: "frameOutput"
        anchors.fill: parent
        fillMode: VideoOutput.Stretch
    }
}
