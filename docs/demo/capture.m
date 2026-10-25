// Injected into PR Wizard by record.py (DYLD_INSERT_LIBRARIES). It films the app's own windows through the window
// server, so it needs no Screen Recording permission, and keeps them offscreen. Commands come from $PRW_DEMO/cmd:
//   rec NAME · stop · select ROW · sidebar ROW · settings · close-settings · default KEY [VALUE] · size W H · target queue|settings
// Frames land in $PRW_DEMO/NAME/00001.png. $PRW_DEMO/ack appears once a command file has run.
#import <AppKit/AppKit.h>
#import <dlfcn.h>
#import <objc/runtime.h>

typedef CGImageRef (*ListImage)(CGRect, uint32_t, uint32_t, uint32_t);

static NSString *dir, *recording, *targetName = @"queue";
static int frame;
static dispatch_queue_t writer;

static BOOL yes(id self, SEL _cmd) { return YES; }

static NSWindow *window(NSString *name) {
    for (NSWindow *w in NSApp.windows) {
        if (!w.isVisible || w.frame.size.width < 300) continue;
        BOOL settings = [@[@"General", @"Lanes", @"Reviewers", @"Fixer"] containsObject:w.title];
        if ([name isEqualToString:@"settings"] == settings) return w;
    }
    return nil;
}

static void collect(NSView *v, NSMutableArray *out) {
    if ([v isKindOfClass:NSTableView.class]) [out addObject:v];
    for (NSView *s in v.subviews) collect(s, out);
}

/// The window's tables from left to right: the sidebar, then the queue.
static NSArray *tables(NSWindow *w) {
    NSMutableArray *out = [NSMutableArray array];
    collect(w.contentView.superview, out);
    return [out sortedArrayUsingComparator:^(NSView *a, NSView *b) {
        return [@([a convertPoint:NSZeroPoint toView:nil].x) compare:@([b convertPoint:NSZeroPoint toView:nil].x)];
    }];
}

static void snap(NSString *path) {
    static ListImage listImage;
    if (!listImage) listImage = (ListImage)dlsym(RTLD_DEFAULT, "CGWindowListCreateImage");
    NSWindow *w = window(targetName);
    CGImageRef image = w ? listImage(CGRectNull, 8, (uint32_t)w.windowNumber, 1 | 8) : NULL;
    if (!image) return;
    NSBitmapImageRep *rep = [[NSBitmapImageRep alloc] initWithCGImage:image];
    CGImageRelease(image);
    dispatch_async(writer, ^{
        [[rep representationUsingType:NSBitmapImageFileTypePNG properties:@{}] writeToFile:path atomically:NO];
    });
}

static void pick(NSTableView *t, NSInteger row) {
    [t selectRowIndexes:[NSIndexSet indexSetWithIndex:row] byExtendingSelection:NO];
}

static void run(NSString *line) {
    NSArray *a = [line componentsSeparatedByString:@" "];
    NSString *op = a[0], *arg = a.count > 1 ? a[1] : nil;
    NSWindow *w = window(targetName);
    if ([op isEqualToString:@"rec"]) {
        recording = [dir stringByAppendingPathComponent:arg];
        [NSFileManager.defaultManager createDirectoryAtPath:recording withIntermediateDirectories:YES attributes:nil error:nil];
        frame = 0;
    } else if ([op isEqualToString:@"stop"]) {
        recording = nil;
    } else if ([op isEqualToString:@"select"]) {
        pick(tables(w).lastObject, arg.integerValue);
    } else if ([op isEqualToString:@"sidebar"]) {
        pick(tables(w).firstObject, arg.integerValue);
    } else if ([op isEqualToString:@"settings"]) {
        NSMenu *app = NSApp.mainMenu.itemArray.firstObject.submenu;
        for (NSMenuItem *i in app.itemArray)
            if ([i.title hasPrefix:@"Settings"]) [app performActionForItemAtIndex:[app indexOfItem:i]];
    } else if ([op isEqualToString:@"close-settings"]) {
        [window(@"settings") close];
    } else if ([op isEqualToString:@"default"]) {
        [NSUserDefaults.standardUserDefaults setObject:(a.count > 2 ? a[2] : @"") forKey:arg];
    } else if ([op isEqualToString:@"size"]) {
        [w setFrame:NSMakeRect(w.frame.origin.x, w.frame.origin.y, [a[1] doubleValue], [a[2] doubleValue]) display:YES];
    } else if ([op isEqualToString:@"target"]) {
        targetName = arg;
    }
}

__attribute__((constructor)) static void start(void) {
    dir = NSProcessInfo.processInfo.environment[@"PRW_DEMO"];
    if (!dir) return;
    writer = dispatch_queue_create("demo.writer", DISPATCH_QUEUE_SERIAL);
    // The app never activates, so it would draw as a background window.
    method_setImplementation(class_getInstanceMethod(NSWindow.class, @selector(isKeyWindow)), (IMP)yes);
    method_setImplementation(class_getInstanceMethod(NSWindow.class, @selector(isMainWindow)), (IMP)yes);
    dispatch_async(dispatch_get_main_queue(), ^{
        [NSTimer scheduledTimerWithTimeInterval:1.0 / 12 repeats:YES block:^(NSTimer *t) {
            if (recording) snap([recording stringByAppendingFormat:@"/%05d.png", ++frame]);
        }];
        [NSTimer scheduledTimerWithTimeInterval:0.05 repeats:YES block:^(NSTimer *t) {
            for (NSWindow *v in NSApp.windows)
                if (v.isVisible && v.frame.origin.x > -9000) [v setFrameOrigin:NSMakePoint(-12000, 200)];
            NSString *cmd = [dir stringByAppendingPathComponent:@"cmd"];
            NSString *text = [NSString stringWithContentsOfFile:cmd encoding:NSUTF8StringEncoding error:nil];
            if (!text) return;
            [NSFileManager.defaultManager removeItemAtPath:cmd error:nil];
            for (NSString *line in [text componentsSeparatedByString:@"\n"])
                if (line.length) run(line);
            [@"" writeToFile:[dir stringByAppendingPathComponent:@"ack"] atomically:YES encoding:NSUTF8StringEncoding error:nil];
        }];
    });
}
