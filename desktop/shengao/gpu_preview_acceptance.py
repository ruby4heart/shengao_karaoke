"""Owned hidden native-Qt instance; actual GPU pixels and CPU fallback."""
from pathlib import Path
import argparse,json,os,time


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--gpu-preview-test',action='store_true');parser.add_argument('--output',required=True)
    args=parser.parse_args();out=Path(args.output).resolve();out.mkdir(parents=True,exist_ok=True)
    os.environ['QT_QPA_PLATFORM']='windows'
    from PySide6.QtCore import Qt,QSize,QRect
    from PySide6.QtGui import QImage
    from PySide6.QtWidgets import QApplication,QWidget
    from PySide6.QtMultimedia import QVideoFrame,QVideoFrameFormat
    from PySide6.QtTest import QTest
    import numpy as np
    from .playback import VideoCanvas
    from .frame_scaler import eligible,preview_size
    app=QApplication([]);host=QWidget();host.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen,True);host.resize(640,360)
    canvas=VideoCanvas(host);canvas.resize(640,360);canvas.show();host.show();checks=[];record={'scope':__doc__,'checks':checks,'passed':False}
    def check(name,condition):
        checks.append({'name':name,'passed':bool(condition)})
        if not condition:raise AssertionError(name)
    def frame_variant(second=False,*,pixel_format=None,color_space=None,color_range=None,transfer=None,viewport=None):
        format=QVideoFrameFormat(QSize(3840,2160),pixel_format if pixel_format is not None else QVideoFrameFormat.PixelFormat.Format_NV12)
        format.setColorSpace(color_space if color_space is not None else QVideoFrameFormat.ColorSpace.ColorSpace_BT709)
        format.setColorRange(color_range if color_range is not None else QVideoFrameFormat.ColorRange.ColorRange_Video)
        format.setColorTransfer(transfer if transfer is not None else QVideoFrameFormat.ColorTransfer.ColorTransfer_BT709)
        if viewport is not None:format.setViewport(viewport)
        width,height=3840,2160
        frame=QVideoFrame(format);assert frame.map(QVideoFrame.MapMode.WriteOnly)
        try:
            y=np.frombuffer(frame.bits(0),np.uint8).reshape(height,frame.bytesPerLine(0))
            interleaved=frame.pixelFormat()==QVideoFrameFormat.PixelFormat.Format_NV12
            if interleaved:uv=np.frombuffer(frame.bits(1),np.uint8).reshape(height//2,frame.bytesPerLine(1))
            else:
                u_index,v_index=(2,1) if frame.pixelFormat()==QVideoFrameFormat.PixelFormat.Format_YV12 else (1,2)
                u=np.frombuffer(frame.bits(u_index),np.uint8).reshape(height//2,frame.bytesPerLine(u_index));v=np.frombuffer(frame.bits(v_index),np.uint8).reshape(height//2,frame.bytesPerLine(v_index))
            for row in range(2):
                for column in range(2):
                    value=(80+row*40+column*20,90+column*60,180-row*50) if not second else (175-row*30-column*20,140-column*40,70+row*40)
                    y[row*(height//2):(row+1)*(height//2),column*(width//2):(column+1)*(width//2)]=value[0]
                    if interleaved:
                        uv[row*(height//4):(row+1)*(height//4),column*(width//2):(column+1)*(width//2):2]=value[1]
                        uv[row*(height//4):(row+1)*(height//4),column*(width//2)+1:(column+1)*(width//2):2]=value[2]
                    else:
                        u[row*(height//4):(row+1)*(height//4),column*(width//4):(column+1)*(width//4)]=value[1]
                        v[row*(height//4):(row+1)*(height//4),column*(width//4):(column+1)*(width//4)]=value[2]
        finally:frame.unmap()
        frame.setStartTime(100000 if not second else 200000);frame.setEndTime(140000 if not second else 240000);return frame
    def pixels(image):
        converted=image.convertToFormat(QImage.Format.Format_RGBA8888)
        return np.frombuffer(converted.constBits(),np.uint8).reshape(converted.height(),converted.bytesPerLine())[:,:converted.width()*4].reshape(converted.height(),converted.width(),4).copy()
    def wait(fn):
        deadline=time.monotonic()+5
        while time.monotonic()<deadline:
            app.processEvents();QTest.qWait(5)
            if fn():return True
        return False
    sizes=[];canvas.frameSizeChanged.connect(lambda w,h:sizes.append((w,h)))
    try:
        frame=frame_variant();original=(frame.startTime(),frame.endTime(),frame.size(),frame.pixelFormat())
        record['device_pixel_ratio']=canvas.devicePixelRatioF();record['source_size']=[frame.width(),frame.height()]
        check('native_gpu_candidate_is_eligible',eligible(frame,preview_size(frame,canvas.width(),canvas.height(),canvas.devicePixelRatioF())))
        canvas.video_frame(frame)
        record['initial_scaler']=canvas.frame_scaler_status()
        check('real_gpu_frame_rendered',canvas.frame_scaler_status()['frames']==1 and not canvas.frame_scaler_status()['error'])
        check('gpu_readback_is_bounded',not canvas.frame.isNull() and max(canvas.frame.width(),canvas.frame.height())<=1922)
        check('original_geometry_is_preserved',sizes==[(3840,2160)] and canvas._source_frame_size==QSize(3840,2160))
        reference=frame.toImage().scaled(canvas.frame.size(),Qt.AspectRatioMode.IgnoreAspectRatio,Qt.TransformationMode.SmoothTransformation)
        a=pixels(canvas.frame)[:,:,:3].astype(np.int16);b=pixels(reference)[:,:,:3].astype(np.int16)
        differences=[]
        for fy in (.25,.75):
            for fx in (.25,.75):
                x=round(canvas.frame.width()*fx);y=round(canvas.frame.height()*fy);differences.extend(np.abs(a[y-8:y+8,x-8:x+8]-b[y-8:y+8,x-8:x+8]).ravel().tolist())
        check('gpu_quadrants_match_original_colour',max(differences)<=3)
        check('source_frame_metadata_is_unchanged',original==(frame.startTime(),frame.endTime(),frame.size(),frame.pixelFormat()))
        check('actual_canvas_paint_matches_frame_pts',wait(lambda:canvas.painted_sequence==1 and canvas.painted_frame_start_us==100000 and canvas.painted_frame_end_us==140000))
        from .project import Project
        from .subtitles import compose
        from studio_backend.model import LyricLine
        caption=Project(lines=[LyricLine('gpu-caption','歌う',100,600)])
        canvas.renderer.set_text(compose(caption));canvas.position=120;canvas.update();app.processEvents()
        gpu_composite=pixels(canvas.grab().toImage())
        glyphs=canvas.renderer.image(canvas.width(),canvas.height(),120).scaled(QSize(gpu_composite.shape[1],gpu_composite.shape[0]),Qt.AspectRatioMode.IgnoreAspectRatio,Qt.TransformationMode.SmoothTransformation)
        core=pixels(glyphs)[:,:,3]>252
        check('subtitle_core_is_visible_on_gpu_background',np.count_nonzero(core)>16)
        first=pixels(canvas.frame);second=frame_variant(True);canvas.video_frame(second)
        check('controlled_sink_does_not_reuse_previous_pixels',canvas.frame_scaler_status()['frames']==2 and np.mean(np.abs(first.astype(np.int16)-pixels(canvas.frame).astype(np.int16)))>20)
        check('second_frame_has_its_own_actual_paint',wait(lambda:canvas.painted_sequence==2 and canvas.painted_frame_start_us==200000))
        for name,options in (
            ('yuv420p',{'pixel_format':QVideoFrameFormat.PixelFormat.Format_YUV420P}),
            ('yv12',{'pixel_format':QVideoFrameFormat.PixelFormat.Format_YV12}),
        ):
            variant=frame_variant(**options);image=canvas._gpu_scaler.convert(variant,preview_size(variant,640,360,canvas.devicePixelRatioF()))
            check('gpu_'+name+'_has_checked_colour',image is not None and eligible(variant,image.size()))
            expected=variant.toImage().scaled(image.size(),Qt.AspectRatioMode.IgnoreAspectRatio,Qt.TransformationMode.SmoothTransformation)
            actual=pixels(image)[:,:,:3].astype(np.int16);reference_pixels=pixels(expected)[:,:,:3].astype(np.int16)
            centres=[np.abs(actual[round(image.height()*fy),round(image.width()*fx)]-reference_pixels[round(image.height()*fy),round(image.width()*fx)]).max() for fy in (.25,.75) for fx in (.25,.75)]
            record.setdefault('colour_deviations',{})[name]=[int(value) for value in centres]
            check('gpu_'+name+'_matches_qt_colour',max(centres)<=3)
        cropped=frame_variant(viewport=QRect(4,4,3832,2152));hdr=frame_variant(color_space=QVideoFrameFormat.ColorSpace.ColorSpace_BT2020,transfer=QVideoFrameFormat.ColorTransfer.ColorTransfer_ST2084)
        check('cropped_metadata_retains_original_path',not eligible(cropped,QSize(640,360)))
        check('hdr_metadata_retains_original_path',not eligible(hdr,QSize(640,360)))
        non709=frame_variant(color_space=QVideoFrameFormat.ColorSpace.ColorSpace_BT601)
        check('bt601_retains_original_path',not eligible(non709,QSize(640,360)))
        canvas.video_frame(non709)
        check('bt601_fallback_matches_original_pixels',canvas.frame==non709.toImage())
        full_range=frame_variant(color_range=QVideoFrameFormat.ColorRange.ColorRange_Full)
        check('full_range_retains_original_path',not eligible(full_range,QSize(640,360)))
        canvas.video_frame(full_range)
        check('full_range_fallback_matches_original_pixels',canvas.frame==full_range.toImage())
        canvas.video_frame(second)
        canvas.grab().save(str(out/'gpu-frame-with-canvas.png'));sequence=canvas.frame_sequence
        canvas.resize(38400,21600)
        check('large_zoom_uses_full_source_without_giant_gpu_target',wait(lambda:canvas.frame.size()==second.size()) and max(canvas._gpu_scaler.view.size().width(),canvas._gpu_scaler.view.size().height())<=1922)
        check('zoom_does_not_invent_a_decoded_frame',canvas.frame_sequence==sequence and canvas._source_frame is None)
        canvas.resize(640,360);canvas.video_frame(second);canvas.resize(680,382);canvas.clear_frame();QTest.qWait(35);app.processEvents()
        check('pending_resize_cannot_resurrect_cleared_frame',canvas.frame.isNull() and canvas._source_frame is None and canvas.painted_frame_start_us is None)
        canvas._gpu_scaler.error='controlled unavailable backend';canvas._gpu_scaler.close();canvas.video_frame(frame)
        check('unavailable_gpu_keeps_original_qt_image',canvas.frame==frame.toImage() and canvas._source_frame is None)
        canvas.resize(640,360);canvas.update();app.processEvents();cpu_composite=pixels(canvas.grab().toImage())
        check('gpu_and_cpu_subtitle_core_pixels_match',np.max(np.abs(gpu_composite[:,:,:3].astype(np.int16)-cpu_composite[:,:,:3].astype(np.int16))[core])<=3)
        check('fallback_keeps_source_pts_and_dimensions',canvas.frame_start_us==100000 and canvas._source_frame_size==QSize(3840,2160))
        check('all_owned_windows_stay_off_screen',all(w.testAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen) for w in QApplication.topLevelWidgets()))
        record['backend']=canvas.frame_scaler_status()['backend'];record['passed']=True
    finally:
        canvas.close_frame_scaler();canvas.renderer.close();host.close();app.processEvents()
        (out/'report.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'passed':record['passed'],'checks':len(checks),'backend':record.get('backend')}))


if __name__=='__main__':main()
