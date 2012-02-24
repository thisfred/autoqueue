%{!?python_sitelib: %global python_sitelib %(%{__python} -c "from distutils.sysconfig import get_python_lib; print(get_python_lib())")}

Name:           python-autoqueue
Version:        1.0.0_bzr351
Release:        1%{?dist}
Summary:        Python library to create a playlist of similar tracks

Group:          Development/Languages
License:        GPLv2
URL:            https://launchpad.net/autoqueue
Source0:        http://launchpad.net/autoqueue/trunk/1.0.0alpha7/+download/autoqueue-%{version}.tar.gz
BuildRoot:      %{_tmppath}/%{name}-%{version}-%{release}-root-%(%{__id_u} -n)

BuildArch:      noarch
BuildRequires:  python-devel, python-distutils-extra

%description
A cross player plug-in that queues up tracks similar to the current one, in a
semi-intelligent and configurable way (it can block playing the same track or 
artist for a configurable amount of time) It works pretty well in creating a 
consistent yet not wholly predictable listening experience.   Similarity is 
looked up on last.fm and/or computed from acoustic analysis if you have 

%package -n rhythmbox-autoqueue
Summary:        Autoqueue plugin for rhythmbox
Group:          Applications/Multimedia
Requires:       python-autoqueue, rhythmbox

%description -n rhythmbox-autoqueue
A plugin for the Rhythmbox music player to create a playlist based on tracks
similar to the currently playing track using python autoqueue.

%package -n quodlibet-autoqueue
Summary:        Autoqueue plugin for quodlibet
Group:          Applications/Multimedia
Requires:       python-autoqueue, quodlibet

%description -n quodlibet-autoqueue
A plugin for the quodlibet music player to create a playlist based on tracks
similar to the currently playing track using python autoqueue.

%prep
%setup -q -n autoqueue


%build
%{__python} setup.py build


%install
rm -rf $RPM_BUILD_ROOT
%{__python} setup.py install -O1 --skip-build --root $RPM_BUILD_ROOT
%{__rm} $RPM_BUILD_ROOT/usr/share/doc/autoqueue/README.txt
%{__mv} $RPM_BUILD_ROOT/usr/share/pyshared/* $RPM_BUILD_ROOT/%{python_sitelib}/

 
%clean
rm -rf $RPM_BUILD_ROOT


%files
%defattr(-,root,root,-)
%doc COPYRIGHT.txt README.txt
%{python_sitelib}/autoqueue*
%{python_sitelib}/mirage*
%{python_sitelib}/mpd_*
%{_libdir}/autoqueue/autoqueue-similarity-service
%{_datadir}/dbus-1/services/org.autoqueue.service

%files -n rhythmbox-autoqueue
%{_libdir}/rhythmbox/plugins/rhythmbox_autoqueue

%files -n quodlibet-autoqueue
%{python_sitelib}/quodlibet/*

%changelog
* Fri Jul 29 2011 Graham White <graham_alton@hotmail.com> 1.0.0_bzr351
- update for builds from Bazaar

* Tue Jul 26 2011 Graham White <graham_alton@hotmail.com> 1.0.0alpha7
- first release
