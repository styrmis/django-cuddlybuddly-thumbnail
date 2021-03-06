import os
import pickle
try:
    from PIL import Image
except ImportError:
    import Image
try:
    from cStringIO import StringIO
except ImportError:
    from StringIO import StringIO
from django.conf import settings
from django.core.files.base import ContentFile, File
from django.core.files.storage import default_storage
from django.db.models.fields.files import FieldFile
from django.utils.encoding import force_unicode, smart_str
from django.utils.hashcompat import md5_constructor
from cuddlybuddly.thumbnail.exceptions import ThumbnailException

FORMATS_TO_EXT = {
    'JPEG': '.jpg',
    'PNG': '.png',
    'GIF': '.gif'
}

def build_thumbnail_name(source, width, height, quality, format=None):
    source = force_unicode(source)
    path, filename = os.path.split(source)
    basename, ext = os.path.splitext(filename)
    
    if format and FORMATS_TO_EXT.has_key(format):
        ext = FORMATS_TO_EXT[format]
    
    name = '%s%s' % (basename, ext.replace(os.extsep, '_'))
    thumbnail = '%s_%sx%s_q%s%s' % (name, width, height, quality, ext)
    return os.path.join(
        getattr(settings, 'CUDDLYBUDDLY_THUMBNAIL_BASEDIR', ''),
        path,
        getattr(settings, 'CUDDLYBUDDLY_THUMBNAIL_SUBDIR', ''),
        thumbnail
    )


class Thumbnail(object):
    def __init__(self, source, width, height, quality=50, format=None):
        self.source = source
        self.width = width
        self.height = height
        self.quality = quality
        self.format = format
        dest = build_thumbnail_name(source, width, height, quality, format)
        self.dest = dest
        self.cache_dir = getattr(settings, 'CUDDLYBUDDLY_THUMBNAIL_CACHE', None)
        
        self.exists = True

        for var in ('width', 'height', 'quality'):
            try:
                setattr(self, var, int(getattr(self, var)))
            except ValueError:
                raise ThumbnailException('Value supplied for \'%s\' is not an int' % var)

        self.generate()

    def __unicode__(self):
        return force_unicode(self.dest)

    def generate(self):
        if hasattr(self.dest, 'write'):
            self._do_generate()
        else:
            do_generate = False
            if self.cache_dir is not None:
                if isinstance(self.source, FieldFile) or \
                   isinstance(self.source, File):
                    source = force_unicode(self.source)
                elif not isinstance(self.source, basestring):
                    source = pickle.dumps(self.source.read())
                    self.source.seek(0)
                else:
                    source = smart_str(force_unicode(self.source))
                source = os.path.join(self.cache_dir,
                                      md5_constructor(source).hexdigest())
                if not isinstance(self.dest, basestring):
                    dest = pickle.dumps(self.dest.read())
                    self.dest.seek(0)
                else:
                    dest = smart_str(force_unicode(self.dest))
                dest = os.path.join(self.cache_dir,
                                      md5_constructor(dest).hexdigest())
            else:
                source = force_unicode(self.source)
                dest = self.dest

            if hasattr(default_storage, 'getmtime') and not self.cache_dir:
                do_generate = default_storage.getmtime(source) > \
                        default_storage.getmtime(dest)
            else:
                if not self.cache_dir:
                    source_cache = os.path.join(settings.MEDIA_ROOT, source)
                    dest_cache = os.path.join(settings.MEDIA_ROOT, dest)
                else:
                    source_cache, dest_cache = source, dest
                try:
                    do_generate = os.path.getmtime(source_cache) > \
                            os.path.getmtime(dest_cache)
                except OSError:
                    do_generate = True

            if do_generate:
                if self.cache_dir is not None:
                    for filename in (source, dest):
                        path = os.path.split(filename)[0]
                        if not os.path.exists(path):
                            os.makedirs(path)
                        open(filename, 'w').close()
                try:
                    self._do_generate()
                except:
                    if self.cache_dir is not None:
                        for filename in (source, dest):
                            if os.path.exists(filename):
                                os.remove(filename)
                    raise

    def _do_generate(self):
        if isinstance(self.source, Image.Image):
            data = self.source
        else:
            try:
                if not hasattr(self.source, 'readline'):
                    if not hasattr(self.source, 'read'):
                        source = force_unicode(self.source)
                        if not default_storage.exists(source):
                            self.source_exists = False
                            # raise ThumbnailException('Source does not exist: %s'
                            #                                                      % self.source)
                        else:
                            file = default_storage.open(source, 'rb')
                            content = ContentFile(file.read())
                            file.close()
                    else:
                        content = ContentFile(self.source.read())
                else:
                    content = ContentFile(self.source.read())
                if self.source_exists:
                    data = Image.open(content)
                else:
                    data = Image.new('RGB', (self.width, self.height), 'white')
            except IOError, detail:
                raise ThumbnailException('%s: %s' % (detail, self.source))
            except MemoryError:
                raise ThumbnailException('Memory Error: %s' % self.source)

        filelike = hasattr(self.dest, 'write')
        if not filelike:
            format = os.path.splitext(self.dest)[1][1:]
            format = format.upper().replace('JPG', 'JPEG')
            dest = StringIO()
        else:
            format = 'JPEG'
            dest = self.dest
            
        if self.format:
            format = self.format
        
        # x, y = [float(v) for v in data.size]
        # xr, yr = [float(v) for v in (self.width, self.height)]
        # r = min(xr / x, yr / y)
        # if r < 1.0:
        #     data = data.resize((int(x * r), int(y * r)),
        #                        resample=Image.ANTIALIAS)
        # if data.mode not in ("L", "RGB", "RGBA"):
        #     data = data.convert("RGB")
        
        data.thumbnail((self.width, self.height), Image.ANTIALIAS)

        try:
            data.save(dest, format=format, quality=self.quality,
                      optimize=1)
        except IOError:
            # Try again, without optimization (PIL can't optimize an image
            # larger than ImageFile.MAXBLOCK, which is 64k by default)
            try:
                data.save(dest, format=format, quality=self.quality)
            except IOError, detail:
                raise ThumbnailException(detail)

        if hasattr(self.source, 'seek'):
            self.source.seek(0)
        if filelike:
            dest.seek(0)
        else:
            filename = force_unicode(self.dest)
            
            if default_storage.exists(filename):
                default_storage.delete(filename)
            default_storage.save(filename, ContentFile(dest.getvalue()))
            dest.close()
